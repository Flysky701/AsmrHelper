"""Application-layer wrapper for standalone ASR workflows."""

from __future__ import annotations

import threading
from pathlib import Path

from ..dto import SubtitleSegment, TranscriptionResult
from ..errors import AppExecutionError, AppValidationError


class AsrService:
    """Stable application-facing facade for ASR operations."""

    def transcribe_file(
        self,
        input_path: str,
        output_path: str | None = None,
        model: str = "base",
        language: str = "ja",
        disable_vad: bool = True,
    ) -> TranscriptionResult:
        source_path = Path(input_path)
        if not source_path.exists():
            raise AppValidationError(f"input file does not exist: {input_path}")

        try:
            from src.core.asr import ASRRecognizer

            recognizer = ASRRecognizer(model_size=model, language=language, disable_vad=disable_vad)
            entries = recognizer.recognize(str(source_path), output_path)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        segments = [
            SubtitleSegment(
                start=float(entry.get("start", 0.0)),
                end=float(entry.get("end", 0.0)),
                text=str(entry.get("text", "")),
            )
            for entry in entries
        ]
        return TranscriptionResult(
            segments=segments,
            output_path=output_path,
            text="\n".join(segment.text for segment in segments if segment.text),
        )


_service: AsrService | None = None
_lock = threading.Lock()


def get_asr_service() -> AsrService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = AsrService()
    return _service
