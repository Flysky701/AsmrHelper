"""User-visible translation reuse behavior; all inference is mocked."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.models import PipelineExecutionContext
from src.core.orchestration.pipeline.planner import build_execution_plan
from src.core.subtitles.translation_reuse import prepare_translation_profile


def subtitle(path, texts):
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
    paths = [subtitle(tmp_path / "audio.wav.vtt", ["こんにちは", "おやすみなさい"]),
             subtitle(tmp_path / "audio.vtt", ["你好", "晚安"])]
    profile = {"version": 1, "source_lang": "ja", "target_lang": "zh", "stages": {
        "asr": {"enabled": True, "provider": "faster_whisper", "options": {}},
        "translate": {"enabled": True, "provider": "deepseek", "options": {"connection_ref": "missing"}},
        **{name: {"enabled": False} for name in ("separate", "align", "tts", "mix", "export")},
    }}
    monkeypatch.setattr(PipelineExecutor, "_try_clear_gpu", lambda self: None)
    return audio, paths, profile


def plan_for(sample, directory, *, prepared=False):
    audio, paths, profile = sample
    if prepared:
        profile = prepare_translation_profile(profile, str(audio), paths)
    return build_execution_plan(PipelineExecutionContext("reuse-test", str(audio), str(directory),
        companion_subtitle_path=paths[0], companion_subtitle_paths=paths, execution_profile=profile))


@pytest.mark.parametrize("align", [False, True])
def test_full_reuse_goes_directly_to_tts_and_preserves_originals(sample, tmp_path, monkeypatch, align):
    audio, paths, profile = sample
    profile["stages"]["align"]["enabled"] = align
    original = deepcopy(profile)
    plan = plan_for(sample, tmp_path / "out", prepared=True)
    assert plan.translation.enabled is False
    assert profile == original
    plan.tts.enabled = True
    plan.tts.provider_options["speech_snapshot"] = {"test": True}
    asr, llm, speech = Mock(), Mock(), Mock()
    aligner = Mock()
    aligner.align_file.side_effect = lambda **kw: {"segments": [
        {**s, "start": s["start"] + 0.1, "end": s["end"] - 0.1} for s in kw["segments"]]}
    speech.synthesize_timeline.return_value = {"experiment_id": "test", "id": "test"}
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    results = PipelineExecutor(asr=asr, llm=llm, aligner=aligner).execute(plan)
    assert results["step_errors"] == {}
    asr.transcribe_file.assert_not_called()
    llm.translate_texts.assert_not_called()
    segments = speech.synthesize_timeline.call_args.args[1]
    assert [s["text"] for s in segments] == ["你好", "晚安"]
    assert [s["original"] for s in segments] == ["こんにちは", "おやすみなさい"]
    assert results["steps"]["translate"]["reused_segments"] == 2


def test_partial_blank_cues_translate_only_missing_and_keep_order(sample, tmp_path):
    audio, paths, profile = sample
    subtitle(tmp_path / "audio.vtt", ["", "晚安"])
    llm = Mock()
    llm.translate_texts.return_value = ["你好（补译）"]
    result = PipelineExecutor(llm=llm).execute(plan_for(sample, tmp_path / "out"))
    assert llm.translate_texts.call_args.kwargs["texts"] == ["こんにちは"]
    records = json.loads(Path(result["translation_records_path"]).read_text(encoding="utf-8"))
    assert [s["translation"] for s in records["segments"]] == ["你好（补译）", "晚安"]
    assert result["steps"]["translate"]["reused_segments"] == 1


def test_language_switch_and_retranslation_never_reuse_old_language_or_overwrite(sample, tmp_path):
    audio, paths, profile = sample
    before = [Path(path).read_bytes() for path in paths]
    plan = plan_for(sample, tmp_path / "out")
    directory = tmp_path / "out"
    directory.mkdir()
    (directory / "translated.txt").write_text("手工旧译文\n\n保留", encoding="utf-8")
    llm = Mock()
    executor = PipelineExecutor(llm=llm)
    for target, reuse in [("en", True), ("zh", False)]:
        plan.target_lang, plan.target_label = target, target
        plan.translation.common_options["reuse_existing"] = reuse
        plan.skip_existing = True
        llm.translate_texts.return_value = ["new first", "new second"]
        segments = [{"start": 0, "end": 1, "text": "こんにちは", "translation": "手工无语言标记"},
                    {"start": 1, "end": 2, "text": "おやすみなさい"}]
        result = {"steps": {}, "step_errors": {}}
        assert executor._execute_translation(plan, segments, directory, result) == ["new first", "new second"]
        assert llm.translate_texts.call_args.kwargs["texts"] == ["こんにちは", "おやすみなさい"]
        assert segments[0]["previous_translation"] == "手工无语言标记"
    assert (directory / "translated.txt").read_text(encoding="utf-8") == "手工旧译文\n\n保留"
    assert [Path(path).read_bytes() for path in paths] == before


@pytest.mark.parametrize("generated", [[""], [], ["one", "extra"]])
def test_incomplete_translation_never_calls_tts(sample, tmp_path, generated, monkeypatch):
    subtitle(tmp_path / "audio.vtt", ["", "晚安"])
    plan = plan_for(sample, tmp_path / "out")
    plan.tts.enabled = True
    llm, speech = Mock(), Mock()
    llm.translate_texts.return_value = generated
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    with pytest.raises(RuntimeError, match="翻译结果"):
        PipelineExecutor(llm=llm).execute(plan)
    speech.synthesize_timeline.assert_not_called()


@pytest.mark.parametrize("source_available", [True, False])
def test_full_reuse_bypasses_readiness_and_missing_connection_for_single_and_batch(sample, tmp_path, monkeypatch, source_available):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService
    from src.app.services.resource_service import ResourceService
    from src.app.services.batch_run_service import BatchRunService
    from src.app.services.task_service import TaskService
    from src.config import config
    audio, paths, profile = sample
    if not source_available:
        Path(paths.pop(0)).unlink()
    monkeypatch.setattr(config, "_config", {"api": {}})
    models, descriptors = Mock(), Mock()
    models.list_models.return_value = []
    descriptors.get_descriptor.return_value = {"runtime_requirements": {}}
    resources = ResourceService(project_root=tmp_path, model_service=models,
        descriptor_service=descriptors, media_probe=lambda path: (True, ""))
    assert resources._check_pipeline_profile(profile, input_path=str(audio)) == []
    assert all(call.args[0] != "llm" for call in descriptors.get_descriptor.call_args_list)
    catalog = Mock()
    assets = [SimpleNamespace(asset_id=str(i), absolute_path=p) for i, p in enumerate([str(audio), *paths])]
    catalog.inspect_paths.side_effect = [[assets[0]], assets[1:]]
    catalog.get_asset.side_effect = lambda aid: assets[int(aid)]
    sessions = Mock()
    sessions.create_session.return_value = SimpleNamespace(session_id="test", resolved_output_dir=str(tmp_path))
    tasks = TaskService()
    pipeline = PipelineService(task_service=tasks, input_catalog_service=catalog, session_service=sessions,
        resource_service=Mock(), workspace_service=Mock(), artifact_service=Mock())
    spec = pipeline.create_pipeline_task_spec(PipelineRequest(input_path=str(audio),
        companion_paths=paths, execution_profile=profile))
    assert spec.execution_profile["stages"]["translate"]["enabled"] is False
    if not source_available:
        plan = build_execution_plan(PipelineExecutionContext("conditional-reuse", str(audio), str(tmp_path / "run"),
            companion_subtitle_path=paths[0], companion_subtitle_paths=paths, execution_profile=spec.execution_profile))
        plan.tts.enabled = True
        asr, llm = Mock(), Mock()
        asr.transcribe_file.return_value.segments = [
            SimpleNamespace(start=i, end=i + 1, text=text) for i, text in enumerate(["こんにちは", "おやすみなさい"])]
        executor = PipelineExecutor(asr=asr, llm=llm)
        executor._execute_tts = Mock(return_value=tmp_path / "tts.wav")
        assert executor.execute(plan)["step_errors"] == {}
        llm.translate_texts.assert_not_called()
        assert [s["translation"] for s in executor._execute_tts.call_args.args[1]] == ["你好", "晚安"]
        subtitle(Path(paths[0]), ["", "晚安"])
        plan.output_dir = str(tmp_path / "run-missing")
        executor._execute_tts.reset_mock()
        with pytest.raises(RuntimeError, match="有效翻译连接"):
            executor.execute(plan)
        executor._execute_tts.assert_not_called()
        llm.translate_texts.assert_not_called()
        subtitle(Path(paths[0]), ["你好", "晚安"])
    batch = BatchRunService(pipeline_orchestrator=Mock())
    monkeypatch.setattr(batch, "_start_monitor_locked", lambda _: None)
    record = batch.create_batch(name="reuse", inputs=[{"path": str(audio), "companion_paths": paths}],
        output_dir="", execution_profile=profile)
    assert "llm_connection_record" not in record.execution_profile
    assert record.execution_profile["stages"]["translate"]["enabled"] is False
    # Choosing a language alone, missing cues, or opting out still requires a connection.
    profile["stages"]["translate"]["options"]["reuse_existing"] = False
    assert any(i["code"] == "LLM_CONNECTION_NOT_READY"
               for i in resources._check_pipeline_profile(profile, input_path=str(audio)))


def test_changed_or_conflicting_sidecars_fail_closed_and_invalidate_recovery(sample, tmp_path):
    from src.core.orchestration.pipeline.recovery import PipelineRecovery
    from src.core.subtitles.translation_reuse import reusable_translations
    audio, paths, profile = sample
    prepared = prepare_translation_profile(profile, str(audio), paths)
    plan = plan_for(sample, tmp_path / "out", prepared=True)
    first = PipelineRecovery(Mock(), "new", None, plan)._fingerprint("translate")
    subtitle(Path(paths[1]), ["新译文", "晚安"])
    second = PipelineRecovery(Mock(), "new", None, plan)._fingerprint("translate")
    assert first != second
    # Same-language manual edits are current evidence, never overwritten by the option.
    other = subtitle(tmp_path / "conflicting.vtt", ["另一个译文", "晚安"])
    segments = [{"start": 0, "end": 1, "text": "こんにちは"}, {"start": 1, "end": 2, "text": "おやすみなさい"}]
    assert reusable_translations(segments, [paths[1], other], "ja", "zh", str(audio)) == ["", "晚安"]
    subtitle(Path(paths[1]), ["hello", "good night"])
    with pytest.raises(ValueError, match="已改变"):
        prepare_translation_profile(prepared, str(audio), paths)


def test_structured_cache_keeps_gaps_and_is_bound_to_original_and_language(sample, tmp_path):
    from src.core.subtitles.translation_reuse import cached_translations
    path = tmp_path / "translations.zh.json"
    segments = [{"start": i, "end": i + 1, "text": f"source-{i}"} for i in range(3)]
    records = [{**s, "source_text": s["text"], "translation": t}
               for s, t in zip(segments, ["第一句", " ", "第三句"], strict=True)]
    path.write_text(json.dumps({"version": 1, "source_lang": "ja", "target_lang": "zh",
        "segments": records}), encoding="utf-8")
    assert cached_translations(path, segments, "ja", "zh") == ["第一句", "", "第三句"]
    assert cached_translations(path, segments, "ja", "en") == ["", "", ""]
    segments[0]["text"] = "changed source"
    assert cached_translations(path, segments, "ja", "zh") == ["", "", "第三句"]
