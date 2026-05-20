"""Compatibility facade for standalone ASR workflows.

.. deprecated::
    Use ``AsrEngineService`` directly for new code. This service exists only
    for backward compatibility with callers that expect the old interface.
"""

from __future__ import annotations

import threading

from ..dto import TranscriptionResult
from .asr_engine_service import AsrEngineService, get_asr_engine_service


class AsrService:
    """Stable application-facing facade for ASR operations."""

    def __init__(self, engine_service: AsrEngineService | None = None) -> None:
        self._engine_service = engine_service or get_asr_engine_service()

    def transcribe_file(
        self,
        input_path: str,
        output_path: str | None = None,
        model: str = "base",
        language: str = "ja",
        disable_vad: bool = True,
    ) -> TranscriptionResult:
        return self._engine_service.transcribe_file(
            input_path=input_path,
            output_path=output_path,
            model=model,
            language=language,
            provider_options={"disable_vad": disable_vad},
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
