"""Selected materials, steps and deliverables stay authoritative; engines are mocks."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from src.app.services.resource_service import ResourceService
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionContext
from src.core.orchestration.pipeline.planner import build_execution_plan
from src.core.orchestration.pipeline.workflow import prepare_workflow, WorkflowValidationError

ALL = ("separate", "asr", "align", "translate", "tts", "mix", "export")


def asset(path, **extra):
    return {"kind": "asset", "path": str(path), **extra}


def previous(stage):
    return {"kind": "stage", "stage": stage}


def profile(enabled, bindings, outputs=None):
    stages = {name: {"enabled": name in enabled, "provider": "unconfigured", "options": {}} for name in ALL}
    stages["tts"]["provider_options"] = {"speech_snapshot": {"test": True}}
    stages["translate"]["options"] = {"connection_ref": "missing"}
    stages["export"]["options"] = {"subtitle_format": "srt"}
    return {"version": 1, "source_lang": "ja", "target_lang": "zh", "stages": stages,
            "workflow": {"version": 1, "bindings": bindings, "outputs": outputs or list(enabled)}}


@pytest.fixture
def materials(tmp_path, monkeypatch):
    audio = tmp_path / "recording.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 32000)
    def subtitle(name, texts):
        path = tmp_path / name
        path.write_text("WEBVTT\n\n" + "\n\n".join(
            f"00:00:0{i}.000 --> 00:00:0{i+1}.000\n{text}" for i,text in enumerate(texts)), encoding="utf-8")
        return path
    zh, ja = subtitle("target.vtt", ["你好", "晚安"]), subtitle("source.vtt", ["こんにちは", "おやすみなさい"])
    speech = Mock()
    speech.pipeline_snapshot.return_value = {"recipe": {"provider_id": "mock", "mode": "preset", "model": "mock"}, "connection": {}}
    speech.connection_context.return_value = {}
    def synthesize(_snapshot, _segments, output, _task_id, **kwargs):
        Path(output).write_bytes(audio.read_bytes())
        return {"id": "mock-assembly", "experiment_id": "mock-experiment"}
    speech.synthesize_timeline.side_effect = synthesize
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    monkeypatch.setattr(PipelineExecutor, "_try_clear_gpu", lambda self: None)
    return audio, zh, ja, speech


def plan_for(p, primary, others, tmp_path):
    return build_execution_plan(PipelineExecutionContext("explicit", str(primary), str(tmp_path / "out"),
        companion_subtitle_paths=list(map(str,others)), execution_profile=p))


def test_subtitle_only_exports_without_audio_or_unselected_engine_checks(materials, tmp_path):
    _, zh, _, speech = materials
    p = profile(["export"], {"export": {"text": asset(zh)}})
    models, descriptors, modules = Mock(), Mock(), Mock(side_effect=AssertionError("unneeded dependency probe"))
    models.list_models.return_value = []
    descriptors.get_descriptor.side_effect = AssertionError("unselected engine")
    resources = ResourceService(project_root=tmp_path, model_service=models, descriptor_service=descriptors,
        module_checker=modules, media_probe=Mock(side_effect=AssertionError("subtitle treated as audio")))
    assert resources._check_pipeline_profile(p, input_path=str(zh)) == []
    models.get_model_status.assert_not_called()
    plan = plan_for(p, zh, [], tmp_path)
    result = PipelineExecutor().execute(plan)
    assert result["last_stage"] == "export"
    assert [a["stage"] for a in result["workflow_outputs"]] == ["export"]
    assert Path(result["primary_output"]).suffix == ".srt"
    assert "你好" in Path(result["primary_output"]).read_text(encoding="utf-8-sig")
    speech.synthesize_timeline.assert_not_called()


def test_same_language_subtitle_tts_only_without_torchaudio_asr_llm(materials, tmp_path, monkeypatch):
    import builtins
    _, zh, _, speech = materials
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.startswith(("torchaudio", "src.core.engines.asr", "src.core.engines.separator", "src.core.engines.llm")):
            raise AssertionError("unselected engine imported")
        return real_import(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",guarded)
    p = profile(["tts"], {"tts": {"text": asset(zh)}})
    # Old persisted controls cannot silently turn stages on or off.
    p["stages"]["translate"]["options"].update(direct_tts=True, reuse_only=True)
    models, descriptors, provider = Mock(), Mock(), Mock()
    models.list_models.return_value = []
    descriptors.get_descriptor.side_effect = AssertionError("unselected readiness")
    provider.probe.return_value = {"ready": True}
    monkeypatch.setattr("src.core.speech.providers.get_provider", lambda _: provider)
    resources = ResourceService(project_root=tmp_path, model_service=models, descriptor_service=descriptors,
        module_checker=Mock(side_effect=AssertionError("unselected dependencies")))
    assert resources._check_pipeline_profile(p, input_path=str(zh)) == []
    provider.probe.assert_called_once()
    plan = plan_for(p, zh, [], tmp_path)
    assert [s.value for s in plan.active_stage_kinds] == ["tts"]
    result = PipelineExecutor().execute(plan)
    assert result["primary_output"] == result["tts_audio_path"]
    assert result["last_stage"] == "tts"
    assert [s["text"] for s in speech.synthesize_timeline.call_args.args[1]] == ["你好", "晚安"]
    assert speech.synthesize_timeline.call_args.kwargs["reference_duration"] == 2


def test_foreign_subtitle_translation_then_tts_uses_selected_predecessor_and_outputs(materials, tmp_path):
    _, _, ja, speech = materials
    p = profile(["translate", "tts", "export"], {"translate": {"text": asset(ja)},
        "tts": {"text": previous("translate")}, "export": {"text": previous("translate")}}, ["tts"])
    before = ja.read_bytes()
    llm = Mock()
    llm.translate_texts.return_value = ["你好", "晚安"]
    result = PipelineExecutor(llm=llm).execute(plan_for(p, ja, [], tmp_path))
    assert llm.translate_texts.call_args.kwargs["texts"] == ["こんにちは", "おやすみなさい"]
    assert [s["text"] for s in speech.synthesize_timeline.call_args.args[1]] == ["你好", "晚安"]
    assert [a["stage"] for a in result["workflow_outputs"]] == ["tts"]
    assert result["exported_subtitle"] is None  # Unselected intermediate is not a deliverable.
    assert ja.read_bytes() == before


def test_full_flow_consumes_only_selected_audio_and_does_not_reuse_unbound_sidecar(materials, tmp_path):
    audio, zh, ja, speech = materials
    p = profile(["separate", "asr", "translate", "tts", "mix", "export"], {
        "separate": {"audio": asset(audio)}, "asr": {"audio": previous("separate")},
        "translate": {"text": previous("asr")}, "tts": {"text": previous("translate")},
        "mix": {"audio": asset(audio), "speech": previous("tts")}, "export": {"text": previous("translate")},
    }, ["mix", "export"])
    separator, asr, llm, mixer = Mock(), Mock(), Mock(), Mock()
    separator.separate.return_value = {"vocals": str(audio)}
    asr.transcribe_file.return_value.segments = [SimpleNamespace(start=0,end=1,text="こんにちは")]
    llm.translate_texts.return_value = ["你好"]
    mixer.mix.side_effect = lambda **kw: Path(kw["output_path"]).write_bytes(audio.read_bytes())
    plan = plan_for(p, audio, [zh,ja], tmp_path)
    result = PipelineExecutor(separator=separator, asr=asr, llm=llm, mixer_factory=lambda *a:mixer).execute(plan)
    asr.transcribe_file.assert_called_once()
    llm.translate_texts.assert_called_once()
    assert mixer.mix.call_args.kwargs["original_path"] == str(audio)
    assert [a["stage"] for a in result["workflow_outputs"]] == ["mix", "export"]
    assert [s["text"] for s in speech.synthesize_timeline.call_args.args[1]] == ["你好"]


def test_asr_subtitle_output_checks_only_asr_and_stops_on_its_failure(materials, tmp_path):
    audio, _, _, speech = materials
    p = profile(["asr", "export"], {"asr": {"audio": asset(audio)}, "export": {"text": previous("asr")}}, ["export"])
    models, descriptors, modules = Mock(), Mock(), Mock(return_value=False)
    models.list_models.return_value = []
    descriptors.get_descriptor.return_value = {"runtime_requirements": {"python_modules": ["selected_asr_dependency"]}}
    resources = ResourceService(project_root=tmp_path, model_service=models, descriptor_service=descriptors,module_checker=modules)
    issues = resources._check_pipeline_profile(p,input_path=str(audio))
    assert {i["stage"] for i in issues} == {"asr"}
    assert [call.args for call in descriptors.get_descriptor.call_args_list] == [("asr", "unconfigured")]
    modules.assert_called_once_with("selected_asr_dependency")
    plan = plan_for(p,audio,[],tmp_path)
    asr = Mock()
    asr.transcribe_file.side_effect = RuntimeError("selected ASR failed")
    with pytest.raises(RuntimeError,match="asr 阶段失败"):
        PipelineExecutor(asr=asr).execute(plan)
    speech.synthesize_timeline.assert_not_called()
    asr.transcribe_file.side_effect = None
    asr.transcribe_file.return_value.segments = [SimpleNamespace(start=0,end=1,text="こんにちは")]
    result = PipelineExecutor(asr=asr).execute(plan)
    assert [item["stage"] for item in result["workflow_outputs"]] == ["export"]
    assert "こんにちは" in Path(result["primary_output"]).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("fault, expected", [
    ("missing", "缺少"), ("foreign", "目标语言"), ("unselected", "未勾选"),
    ("cycle", "循环"), ("output", "产出"), ("not_in_pool", "所选输入"),
])
def test_missing_or_conflicting_choices_never_enable_steps_or_fallback(materials, fault, expected):
    _, zh, ja, _ = materials
    p = profile(["tts"], {"tts": {"text": asset(zh)}})
    paths = [str(zh),str(ja)]
    if fault == "missing":
        p["workflow"]["bindings"]["tts"].clear()  # Multiple candidates exist, none is implicitly selected.
    elif fault == "foreign":
        p["workflow"]["bindings"]["tts"]["text"] = asset(ja)
    elif fault == "unselected":
        p["workflow"]["bindings"]["tts"]["text"] = previous("translate")
    elif fault == "cycle":
        p["workflow"]["bindings"]["tts"]["text"] = previous("tts")
    elif fault == "output":
        p["workflow"]["outputs"] = ["mix"]
    else:
        paths = []
        p["workflow"]["bindings"]["tts"]["text"] = asset(ja)
    before = deepcopy(p)
    with pytest.raises(WorkflowValidationError,match=expected):
        prepare_workflow(p,str(zh),paths)
    assert p == before


def test_unknown_language_confirmation_pairing_and_queued_material_changes(materials, tmp_path):
    audio, zh, _, _ = materials
    ambiguous = tmp_path / "ambiguous.vtt"
    ambiguous.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n12345",encoding="utf-8")
    reference = asset(ambiguous)
    p = profile(["tts"], {"tts": {"text": reference}})
    with pytest.raises(ValueError,match="确认.*语言"):
        prepare_workflow(p,str(ambiguous),[])
    reference.update(language="zh",language_confirmed=True,audio_path=str(audio))
    with pytest.raises(ValueError,match="对应关系"):
        prepare_workflow(p,str(ambiguous),[str(audio)])
    reference["pair_confirmed"] = True
    frozen = prepare_workflow(p,str(ambiguous),[str(audio)])
    assert frozen["workflow"]["languages"]["tts"] == "zh"
    restored = json.loads(json.dumps(frozen))
    assert prepare_workflow(restored,str(ambiguous),[str(audio)])["workflow"] == frozen["workflow"]
    ambiguous.write_text(zh.read_text(encoding="utf-8"),encoding="utf-8")
    with pytest.raises(ValueError,match="提交后改变"):
        prepare_workflow(restored,str(ambiguous),[str(audio)])


def test_mixing_subtitle_speech_requires_explicit_audio_correspondence(materials):
    audio, zh, _, _ = materials
    reference = asset(zh)
    p = profile(["tts", "mix"], {"tts": {"text": reference},
        "mix": {"audio": asset(audio), "speech": previous("tts")}}, ["mix"])
    with pytest.raises(ValueError,match="对应同一录音"):
        prepare_workflow(p,str(zh),[str(audio)])
    reference.update(audio_path=str(audio),pair_confirmed=True)
    prepared = prepare_workflow(p,str(zh),[str(audio)])
    assert not prepared["stages"]["separate"]["enabled"]
    content = zh.read_text(encoding="utf-8").replace("00:00:02.000", "00:00:09.000")
    zh.write_text(content,encoding="utf-8")
    with pytest.raises(ValueError,match="超出"):
        prepare_workflow(p,str(zh),[str(audio)])


def test_malformed_mix_bindings_report_missing_inputs_without_mutating_choices(materials):
    audio, _, _, _ = materials
    bindings = [None, [], "invalid", {"audio": asset(audio), "speech": None},
                {"audio": asset(audio), "speech": []},
                {"audio": asset(audio), "speech": {"kind": "stage", "stage": []}}]
    for binding in bindings:
        p = profile(["mix"], {"mix": binding})
        before = deepcopy(p)
        with pytest.raises(WorkflowValidationError) as caught:
            prepare_workflow(p, str(audio), [])
        assert {issue["stage"] for issue in caught.value.issues} == {"mix"}
        assert p == before


def test_submission_snapshot_supports_subtitle_primary_and_registers_selected_outputs(materials, tmp_path):
    from src.api.http.schemas.pipeline_runs import PipelineRunCreateRequest
    from src.api.http.routes.pipeline_runs import _to_v1_pipeline_request
    from src.app.services.pipeline_service import PipelineService
    from src.app.services.task_service import TaskService
    from src.config import config
    _, zh, _, _ = materials
    p = profile(["export"], {"export": {"text": asset(zh)}})
    body = PipelineRunCreateRequest(input={"path":str(zh)},execution_profile=p)
    request = _to_v1_pipeline_request(body)
    catalog, sessions, artifacts = Mock(), Mock(), Mock()
    primary=SimpleNamespace(asset_id="subtitle",absolute_path=str(zh))
    catalog.inspect_paths.return_value=[primary]
    catalog.get_asset.return_value=primary
    sessions.create_session.return_value=SimpleNamespace(session_id="s",resolved_output_dir=str(tmp_path))
    service=PipelineService(task_service=TaskService(),input_catalog_service=catalog,session_service=sessions,
        workspace_service=Mock(),resource_service=Mock(),artifact_service=artifacts)
    # No translation or synthesis configuration is needed for this selected output.
    assert config is not None
    spec=service.create_pipeline_task_spec(request)
    catalog.discover_companions.assert_not_called()
    frozen=spec.execution_profile
    plan=plan_for(frozen,zh,[],tmp_path)
    result=PipelineExecutor().execute(plan)
    service._register_pipeline_artifacts(task_id="explicit",results=result,mix_path=None,exported_subtitle=result["exported_subtitle"])
    assert artifacts.register_artifact.call_count==1
    assert artifacts.register_artifact.call_args.kwargs["stage"]=="export"
    assert artifacts.register_artifact.call_args.kwargs["is_primary"] is True
