"""Direct subtitle synthesis: no model imports or external calls are allowed."""
import builtins
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from src.app.dto import PipelineRequest
from src.app.services.pipeline_service import PipelineService
from src.app.services.resource_service import ResourceService
from src.app.services.task_service import TaskService
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionContext, StageKind
from src.core.orchestration.pipeline.planner import build_execution_plan
from src.core.subtitles.translation_reuse import prepare_translation_profile


def write_subtitle(path, texts):
    path.write_text("WEBVTT\n\n" + "\n\n".join(
        f"00:00:0{i}.000 --> 00:00:0{i + 1}.000\n{text}"
        for i, text in enumerate(texts)), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 32000)
    subtitle = write_subtitle(tmp_path / "audio.vtt", ["你好", "晚安"])
    profile = {"version": 1, "source_lang": "ja", "target_lang": "zh", "stages": {
        name: {"enabled": True, "provider": "unavailable", "options": {}}
        for name in ("separate", "asr", "align", "translate", "tts", "mix", "export")}}
    profile["stages"]["translate"]["options"] = {
        "reuse_existing": True, "direct_tts": True, "connection_ref": "missing"}
    profile["stages"]["mix"]["options"] = {"original_volume": 0.85, "tts_volume_ratio": 0.5}
    monkeypatch.setattr(PipelineExecutor, "_try_clear_gpu", lambda self: None)
    from src.config import config
    monkeypatch.setattr(config, "_config", {"api": {}})
    return str(audio), [subtitle], profile


def make_plan(sample, directory):
    audio, paths, profile = sample
    return build_execution_plan(PipelineExecutionContext("direct-test", audio, str(directory),
        companion_subtitle_paths=paths, execution_profile=profile))


def test_direct_target_only_bypasses_unavailable_engines_through_submission_readiness_and_execution(sample, tmp_path, monkeypatch):
    audio, paths, profile = sample
    original = deepcopy(profile)
    subtitle_bytes = Path(paths[0]).read_bytes()
    speech = Mock()
    snapshot = {"recipe": {"provider_id": "mock", "model": "mock", "mode": "preset"}, "connection": {}}
    speech.pipeline_snapshot.return_value = snapshot
    speech.connection_context.return_value = {}
    provider = Mock()
    provider.probe.return_value = {"ready": True}
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    monkeypatch.setattr("src.core.speech.providers.get_provider", lambda _: provider)
    imports = []
    real_import = builtins.__import__
    def no_torchaudio(name, *args, **kwargs):
        if name.split(".")[0] == "torchaudio":
            imports.append(name)
            raise ModuleNotFoundError("No module named 'torchaudio'")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_torchaudio)
    descriptors, models, modules, ffmpeg = Mock(), Mock(), Mock(return_value=False), Mock(return_value=(False, "missing"))
    models.list_models.return_value = []
    models.get_model_status.side_effect = AssertionError("irrelevant model readiness")
    descriptors.get_descriptor.side_effect = AssertionError("irrelevant engine readiness")
    resources = ResourceService(project_root=tmp_path, model_service=models, descriptor_service=descriptors,
        module_checker=modules, ffmpeg_checker=ffmpeg, media_probe=lambda _: (True, ""))
    monkeypatch.setattr(resources, "check_required_resources", lambda: [])
    ready = resources.check_task_readiness(task_type="pipeline", execution_profile=profile, input_path=audio)
    assert ready["ready"], ready["issues"]
    descriptors.get_descriptor.assert_not_called()
    models.get_model_status.assert_not_called()
    modules.assert_not_called()
    ffmpeg.assert_not_called()
    provider.probe.assert_called_once()
    assets = [SimpleNamespace(asset_id=str(i), absolute_path=p) for i, p in enumerate([audio, *paths])]
    catalog, sessions, artifacts = Mock(), Mock(), Mock()
    catalog.inspect_paths.side_effect = [[assets[0]], assets[1:]]
    catalog.get_asset.side_effect = lambda aid: assets[int(aid)]
    sessions.create_session.return_value = SimpleNamespace(session_id="test", resolved_output_dir=str(tmp_path))
    service = PipelineService(task_service=TaskService(), input_catalog_service=catalog, session_service=sessions,
        resource_service=resources, workspace_service=Mock(), artifact_service=artifacts)
    spec = service.create_pipeline_task_spec(PipelineRequest(input_path=audio, companion_paths=paths, execution_profile=profile))
    plan = make_plan((audio, paths, spec.execution_profile), tmp_path / "out")
    assert plan.active_stage_kinds == [StageKind.TTS]
    assert plan.mix.enabled is False and plan.subtitle.enabled is True
    assert profile == original
    executor = PipelineExecutor()
    for method in ("_execute_separation", "_execute_asr", "_execute_alignment", "_execute_translation", "_execute_mix"):
        monkeypatch.setattr(executor, method, Mock(side_effect=AssertionError("unneeded stage executed")))
    def synthesize(_snapshot, segments, output, _task_id, **kwargs):
        assert [(s["text"], s["original"], s["start_time"], s["end_time"]) for s in segments] == [
            ("你好", "", 0, 1), ("晚安", "", 1, 2)]
        assert kwargs["reference_duration"] == 4
        Path(output).write_bytes(Path(audio).read_bytes())
        return {"id": "mock-assembly", "experiment_id": "mock-experiment"}
    speech.synthesize_timeline.side_effect = synthesize
    # An old mix file in the output directory must not become this task's primary output.
    output = Path(plan.output_dir)
    output.mkdir()
    (output / "audio_mix.wav").write_bytes(b"old output")
    result = executor.execute(plan)
    assert result["step_errors"] == {}
    assert set(result["steps"]) == {"tts"}
    assert result["mix_path"] is None
    assert result["primary_output"] == result["tts_audio_path"]
    assert Path(result["exported_subtitle"]).name == "audio_zh.srt"
    assert "你好" in Path(result["exported_subtitle"]).read_text(encoding="utf-8-sig")
    assert Path(paths[0]).read_bytes() == subtitle_bytes
    service._register_pipeline_artifacts(task_id="test", results=result, mix_path=None,
        exported_subtitle=result["exported_subtitle"])
    primary = [call.kwargs for call in artifacts.register_artifact.call_args_list if call.kwargs["is_primary"]]
    assert [item["artifact_type"] for item in primary] == ["audio.tts"]
    assert imports == []


@pytest.mark.parametrize("problem, message", [
    ("language", "目标语言"), ("blank", "空白"), ("time", "超出"),
    ("missing", "未找到"), ("partial", "缺少对应原文"), ("untimed", "无法解析"),
])
def test_inadequate_subtitles_stop_direct_mode_with_specific_reason(sample, tmp_path, problem, message):
    audio, paths, profile = sample
    if problem == "language":
        profile["target_lang"] = "en"
    elif problem == "blank":
        write_subtitle(Path(paths[0]), ["", "晚安"])
    elif problem == "time":
        Path(paths[0]).write_text("WEBVTT\n\n00:00:00.000 --> 00:00:09.000\n你好", encoding="utf-8")
    elif problem == "missing":
        Path(paths[0]).unlink()
        paths.clear()
    elif problem == "untimed":
        with Path(paths[0]).open("a", encoding="utf-8") as stream:
            stream.write("\n\n第三句没有时间轴")
    else:
        paths.append(write_subtitle(tmp_path / "audio.wav.vtt", ["こんにちは", "おやすみなさい"]))
        write_subtitle(Path(paths[0]), ["你好"])
    with pytest.raises(ValueError, match=message):
        prepare_translation_profile(profile, audio, paths)


def test_changed_queued_subtitle_cannot_use_old_audio_or_synthesize_without_review(sample, tmp_path, monkeypatch):
    from src.core.orchestration.pipeline.recovery import PipelineRecovery
    audio, paths, profile = sample
    prepared = prepare_translation_profile(profile, audio, paths)
    plan = make_plan((audio, paths, prepared), tmp_path / "out")
    before = PipelineRecovery(Mock(), "new", None, plan)._upstream
    write_subtitle(Path(paths[0]), ["新的译文", "晚安"])
    assert PipelineRecovery(Mock(), "new", None, plan)._upstream != before
    speech = Mock()
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    with pytest.raises(ValueError, match="字幕已改变"):
        PipelineExecutor().execute(plan)
    speech.synthesize_timeline.assert_not_called()


def test_normal_pipeline_keeps_separation_asr_mix_and_partial_translation_fallback(sample, tmp_path):
    audio, paths, profile = sample
    profile["stages"]["translate"]["options"]["direct_tts"] = False
    paths.append(write_subtitle(tmp_path / "audio.wav.vtt", ["こんにちは", "おやすみなさい"]))
    write_subtitle(Path(paths[0]), ["你好", ""])
    prepared = prepare_translation_profile(profile, audio, paths)
    plan = make_plan((audio, paths, prepared), tmp_path / "out")
    assert plan.separation.enabled and plan.asr.enabled and plan.alignment.enabled and plan.translation.enabled and plan.mix.enabled
    assert plan.mix.original_volume == 0.85 and plan.mix.tts_volume_ratio == 0.5
    llm = Mock()
    llm.translate_texts.return_value = ["补充译文"]
    segments = [{"start": 0, "end": 1, "text": "こんにちは"}, {"start": 1, "end": 2, "text": "おやすみなさい"}]
    result = {"steps": {}, "step_errors": {}}
    assert PipelineExecutor(llm=llm)._execute_translation(plan, segments, tmp_path, result) == ["你好", "补充译文"]
    assert llm.translate_texts.call_args.kwargs["texts"] == ["おやすみなさい"]
