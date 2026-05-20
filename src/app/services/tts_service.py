"""Compatibility facade for standalone TTS workflows.

.. deprecated::
    Use ``TtsEngineService`` directly for new code. This service exists only
    for backward compatibility with callers that expect the old interface.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..dto import SynthesisResult
from ..errors import AppValidationError
from .tts_engine_service import TtsEngineService, get_tts_engine_service


class TtsService:
    """Stable application-facing facade for TTS operations."""

    def __init__(self, engine_service: TtsEngineService | None = None) -> None:
        self._engine_service = engine_service or get_tts_engine_service()

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

        text = source_path.read_text(encoding="utf-8")
        return self._engine_service.synthesize_text(
            text=text,
            output_path=output_path,
            provider=engine,
            common_options={"voice": voice},
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
