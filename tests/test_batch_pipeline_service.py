from __future__ import annotations

from pathlib import Path

import pytest

from src.app.dto import ArtifactSet, BatchPipelineRequest, PipelineResult
from src.app.errors import AppValidationError
from src.app.services.batch_pipeline_service import BatchPipelineService


class _DummyPipelineService:
    def __init__(self) -> None:
        self.requests = []

    def run_audio_pipeline(self, request):
        self.requests.append(request)
        if request.input_path.endswith("fail.wav"):
            raise RuntimeError("boom")
        output = Path(request.output_dir or request.batch_root_dir) / "final_mix.wav"
        return PipelineResult(
            success=True,
            input_path=request.input_path,
            artifacts=ArtifactSet(primary_output=str(output)),
            mix_path=str(output),
        )


def test_discover_audio_files_returns_sorted_matches(tmp_path):
    (tmp_path / "b.wav").write_bytes(b"audio")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a.mp3").write_bytes(b"audio")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    service = BatchPipelineService()
    files = service.discover_audio_files(str(tmp_path))

    assert [path.name for path in files] == ["b.wav", "a.mp3"]


def test_run_batch_uses_explicit_file_list(tmp_path):
    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    pipeline_service = _DummyPipelineService()
    service = BatchPipelineService(pipeline_service=pipeline_service)

    result = service.run_batch(
        BatchPipelineRequest(
            input_files=[str(input_path)],
            output_base_dir=str(tmp_path / "out"),
            tts_engine="qwen3",
            tts_voice="Vivian",
            tts_speed=1.2,
            original_volume=0.7,
            tts_volume_ratio=0.45,
            tts_delay=125,
            vocal_model="hdemucs_mmi",
            asr_model="small",
        )
    )

    assert result.success_count == 1
    request = pipeline_service.requests[0]
    assert request.input_path == str(input_path)
    assert request.output_dir.endswith("demo")
    assert request.tts_engine == "qwen3"
    assert request.tts_voice == "Vivian"
    assert request.tts_speed == 1.2
    assert request.original_volume == 0.7
    assert request.tts_volume_ratio == 0.45
    assert request.tts_delay == 125
    assert request.vocal_model == "hdemucs_mmi"
    assert request.asr_model == "small"


def test_run_batch_uses_input_dir_when_provided(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"a")
    (tmp_path / "b.wav").write_bytes(b"b")
    pipeline_service = _DummyPipelineService()
    service = BatchPipelineService(pipeline_service=pipeline_service)

    result = service.run_batch(BatchPipelineRequest(input_dir=str(tmp_path)))

    assert result.total_count == 2
    assert len(pipeline_service.requests) == 2


def test_run_batch_skips_existing_output(tmp_path):
    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    output_dir = tmp_path / "out" / "demo"
    output_dir.mkdir(parents=True)
    final_mix = output_dir / "final_mix.wav"
    final_mix.write_bytes(b"mix")

    pipeline_service = _DummyPipelineService()
    service = BatchPipelineService(pipeline_service=pipeline_service)
    result = service.run_batch(
        BatchPipelineRequest(
            input_files=[str(input_path)],
            output_base_dir=str(tmp_path / "out"),
            skip_existing=True,
        )
    )

    assert result.skipped_count == 1
    assert result.items[0].output == str(final_mix)
    assert pipeline_service.requests == []


def test_run_batch_collects_failures_without_stopping(tmp_path):
    ok_path = tmp_path / "ok.wav"
    fail_path = tmp_path / "fail.wav"
    skip_path = tmp_path / "skip.wav"
    ok_path.write_bytes(b"ok")
    fail_path.write_bytes(b"fail")
    skip_path.write_bytes(b"skip")
    skip_dir = tmp_path / "out" / "skip"
    skip_dir.mkdir(parents=True)
    (skip_dir / "final_mix.wav").write_bytes(b"mix")

    pipeline_service = _DummyPipelineService()
    service = BatchPipelineService(pipeline_service=pipeline_service)
    result = service.run_batch(
        BatchPipelineRequest(
            input_files=[str(ok_path), str(fail_path), str(skip_path)],
            output_base_dir=str(tmp_path / "out"),
        )
    )

    assert [item.status for item in result.items] == ["success", "failed", "skipped"]
    assert result.failed_count == 1
    assert result.skipped_count == 1
    assert result.success_count == 1


def test_run_batch_rejects_invalid_requests(tmp_path):
    service = BatchPipelineService()

    with pytest.raises(AppValidationError, match="either input_files or input_dir is required"):
        service.run_batch(BatchPipelineRequest())

    with pytest.raises(AppValidationError, match="mutually exclusive"):
        service.run_batch(
            BatchPipelineRequest(
                input_files=[str(tmp_path / "demo.wav")],
                input_dir=str(tmp_path),
            )
        )

    with pytest.raises(AppValidationError, match="input directory does not exist"):
        service.run_batch(BatchPipelineRequest(input_dir=str(tmp_path / "missing")))
