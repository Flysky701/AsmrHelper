"""Application-layer wrapper for standalone TTS workflows."""

from __future__ import annotations

import threading
from pathlib import Path

from ..dto import SynthesisResult
from ..errors import AppExecutionError, AppValidationError


class TtsService:
    """Stable application-facing facade for TTS operations."""

    def synthesize_file(
        self,
        input_path: str,
        output_path: str,
        engine: str = "edge",
        voice: str = "zh-CN-XiaoxiaoNeural",
    ) -> SynthesisResult:
        source_path = Path(input_path)
        if not source_path.exists():
            raise AppValidationError(f"input file does not exist: {input_path}")

        try:
            from src.core.tts import TTSEngine

            text = source_path.read_text(encoding="utf-8")
            tts_engine = TTSEngine(engine=engine, voice=voice)
            result_path = tts_engine.synthesize(text, output_path)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return SynthesisResult(
            engine=engine,
            voice=voice,
            output_path=result_path,
        )


_service: TtsService | None = None
_lock = threading.Lock()


def get_tts_service() -> TtsService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TtsService()
    return _service
