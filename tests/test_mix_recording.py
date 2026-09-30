"""Audio result and optional experiment history have separate failure boundaries."""
import logging
from types import SimpleNamespace
from unittest.mock import Mock

from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.result_mapper import ArtifactResultMapper
from src.app.services import speech_service


def run_mix(tmp_path, monkeypatch, *, record_error=None, mix_error=None):
    source, tts, output = (tmp_path / name for name in ("source.wav", "tts.wav", "mix.wav"))
    source.write_bytes(b"source")
    tts.write_bytes(b"tts")
    recorder = Mock(side_effect=record_error)
    monkeypatch.setattr(speech_service, "get_speech_service",
                        lambda: SimpleNamespace(record_formal_mix=recorder))

    def mix(**kwargs):
        assert kwargs["output_path"] == str(output)
        if mix_error:
            raise mix_error
        output.write_bytes(b"completed-mix")

    executor = PipelineExecutor(mixer_factory=lambda *_: SimpleNamespace(mix=mix))
    plan = SimpleNamespace(mix=SimpleNamespace(original_volume=.8, tts_volume_ratio=.5, tts_delay_ms=0))
    results = {"steps": {}, "step_errors": {}, "speech_experiment_id": "experiment-1"}
    executor._execute_mix(plan, source, tts, output, results)
    return results, output, recorder


def test_successful_mix_still_records_experiment(tmp_path, monkeypatch):
    results, output, recorder = run_mix(tmp_path, monkeypatch)
    assert output.read_bytes() == b"completed-mix"
    assert results["steps"]["mixer"]["output"] == str(output)
    assert not results["step_errors"]
    assert "warnings" not in results["steps"]["mixer"]
    assert recorder.call_count == 1


def test_history_failure_preserves_audio_and_exposes_warning(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        results, output, recorder = run_mix(tmp_path, monkeypatch, record_error=OSError("disk unavailable"))
    normalized = ArtifactResultMapper.normalize_results(results)
    assert output.read_bytes() == b"completed-mix"
    assert normalized["steps"]["mixer"]["output"] == str(output)
    assert not normalized["step_errors"] and not normalized["error"]
    assert normalized["steps"]["mixer"]["warnings"]
    assert "附加实验记录保存失败" in caplog.text
    assert recorder.call_count == 1


def test_real_mix_failure_stays_failed_and_does_not_record(tmp_path, monkeypatch):
    results, output, recorder = run_mix(tmp_path, monkeypatch, mix_error=RuntimeError("encoder failed"))
    normalized = ArtifactResultMapper.normalize_results(results)
    assert not output.exists()
    assert normalized["step_errors"] == {"mixer": "encoder failed"}
    assert "output" not in normalized["steps"]["mixer"]
    assert "warnings" not in normalized["steps"]["mixer"]
    recorder.assert_not_called()
