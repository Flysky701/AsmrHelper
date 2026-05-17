from __future__ import annotations

from pathlib import Path

import pytest

from src.app.dto.script_subtitle import ScriptSubtitleRequest
from src.app.errors import AppExecutionError, AppValidationError
from src.app.services.script_subtitle_service import ScriptSubtitleService


class _DummyPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, **kwargs):
        self.calls.append(("full", kwargs))
        return kwargs["output_path"]

    def run_from_existing_vtt(self, **kwargs):
        self.calls.append(("from_vtt", kwargs))
        return kwargs["output_path"]

    def run_text_only(self, **kwargs):
        self.calls.append(("text_only", kwargs))
        return "line one\n\nline two\n"


def _patch_pipeline(monkeypatch, pipeline: _DummyPipeline) -> None:
    monkeypatch.setattr(
        "src.app.services.script_subtitle_service._load_pipeline_runtime",
        lambda: lambda: pipeline,
    )


def test_run_full_delegates_to_core_pipeline(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    audio_path = tmp_path / "audio.wav"
    output_path = tmp_path / "out" / "result.vtt"
    script_path.write_text("hello", encoding="utf-8")
    audio_path.write_bytes(b"audio")

    pipeline = _DummyPipeline()
    _patch_pipeline(monkeypatch, pipeline)

    service = ScriptSubtitleService()
    result = service.run_full(
        ScriptSubtitleRequest(
            script_path=str(script_path),
            audio_path=str(audio_path),
            output_path=str(output_path),
            fmt="vtt",
            use_llm_clean=False,
            asr_model_size="small",
            asr_language="ja",
            track_index=1,
            vertical_mode="horizontal",
        )
    )

    assert result.mode == "full"
    assert result.output_path == str(output_path)
    assert output_path.parent.exists()
    mode, kwargs = pipeline.calls[0]
    assert mode == "full"
    assert kwargs["audio_path"] == str(audio_path)
    assert kwargs["fmt"] == "vtt"
    assert kwargs["track_index"] == 1
    assert kwargs["vertical_mode"] == "horizontal"


def test_run_from_existing_vtt_delegates_to_core_pipeline(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    vtt_path = tmp_path / "source.vtt"
    output_path = tmp_path / "out" / "result.srt"
    script_path.write_text("hello", encoding="utf-8")
    vtt_path.write_text("WEBVTT\n", encoding="utf-8")

    pipeline = _DummyPipeline()
    _patch_pipeline(monkeypatch, pipeline)

    service = ScriptSubtitleService()
    result = service.run_from_existing_vtt(
        ScriptSubtitleRequest(
            script_path=str(script_path),
            vtt_path=str(vtt_path),
            output_path=str(output_path),
            fmt="srt",
        )
    )

    assert result.mode == "from_vtt"
    assert result.output_path == str(output_path)
    mode, kwargs = pipeline.calls[0]
    assert mode == "from_vtt"
    assert kwargs["vtt_path"] == str(vtt_path)
    assert kwargs["fmt"] == "srt"


def test_run_text_only_returns_line_count(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")

    pipeline = _DummyPipeline()
    _patch_pipeline(monkeypatch, pipeline)

    service = ScriptSubtitleService()
    result = service.run_text_only(
        ScriptSubtitleRequest(
            script_path=str(script_path),
            output_path=str(tmp_path / "out.txt"),
        )
    )

    assert result.mode == "text_only"
    assert result.line_count == 2
    assert result.text.startswith("line one")
    assert pipeline.calls[0][0] == "text_only"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (ScriptSubtitleRequest(script_path="", output_path="out.vtt"), "script_path is required"),
        (
            ScriptSubtitleRequest(script_path="missing.txt", output_path="out.vtt"),
            "script file does not exist",
        ),
        (
            ScriptSubtitleRequest(
                script_path="missing.txt",
                output_path="out.vtt",
                vertical_mode="diagonal",
            ),
            "script file does not exist",
        ),
    ],
)
def test_common_validation_errors(payload, message, tmp_path):
    service = ScriptSubtitleService()
    if payload.script_path and payload.script_path != "missing.txt":
        Path(payload.script_path).write_text("hello", encoding="utf-8")

    with pytest.raises(AppValidationError, match=message):
        service.run_text_only(payload)


def test_invalid_vertical_mode_rejected(tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="unsupported vertical_mode"):
        service.run_text_only(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                output_path=str(tmp_path / "out.txt"),
                vertical_mode="diagonal",
            )
        )


def test_invalid_track_index_rejected(tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="track_index must be >= 0"):
        service.run_text_only(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                output_path=str(tmp_path / "out.txt"),
                track_index=-1,
            )
        )


def test_invalid_subtitle_format_rejected(tmp_path):
    script_path = tmp_path / "script.txt"
    audio_path = tmp_path / "audio.wav"
    script_path.write_text("hello", encoding="utf-8")
    audio_path.write_bytes(b"audio")
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="unsupported subtitle format"):
        service.run_full(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                audio_path=str(audio_path),
                output_path=str(tmp_path / "out.foo"),
                fmt="foo",
            )
        )


def test_missing_audio_path_rejected(tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="audio_path is required"):
        service.run_full(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                output_path=str(tmp_path / "out.vtt"),
            )
        )


def test_missing_vtt_path_rejected(tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="vtt_path is required"):
        service.run_from_existing_vtt(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                output_path=str(tmp_path / "out.vtt"),
            )
        )


def test_value_error_from_core_is_mapped_to_validation_error(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    audio_path = tmp_path / "audio.wav"
    script_path.write_text("hello", encoding="utf-8")
    audio_path.write_bytes(b"audio")

    class _ValueErrorPipeline(_DummyPipeline):
        def run(self, **kwargs):
            raise ValueError("bad format")

    _patch_pipeline(monkeypatch, _ValueErrorPipeline())
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="bad format"):
        service.run_full(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                audio_path=str(audio_path),
                output_path=str(tmp_path / "out.vtt"),
            )
        )


def test_unexpected_core_error_is_mapped_to_execution_error(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    audio_path = tmp_path / "audio.wav"
    script_path.write_text("hello", encoding="utf-8")
    audio_path.write_bytes(b"audio")

    class _BoomPipeline(_DummyPipeline):
        def run(self, **kwargs):
            raise RuntimeError("boom")

    _patch_pipeline(monkeypatch, _BoomPipeline())
    service = ScriptSubtitleService()

    with pytest.raises(AppExecutionError, match="boom"):
        service.run_full(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                audio_path=str(audio_path),
                output_path=str(tmp_path / "out.vtt"),
            )
        )
