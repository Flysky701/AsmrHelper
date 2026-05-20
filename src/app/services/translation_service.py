"""Application-layer wrapper for standalone translation workflows."""

from __future__ import annotations

import threading
from pathlib import Path

from ..dto import TranslationResult
from ..errors import AppValidationError
from .llm_capability_service import LlmCapabilityService, get_llm_capability_service


class TranslationService:
    """Stable application-facing facade for translation operations."""

    def __init__(self, llm_service: LlmCapabilityService | None = None) -> None:
        self._llm_service = llm_service or get_llm_capability_service()

    def translate_file(
        self,
        input_path: str,
        output_path: str | None = None,
        provider: str = "deepseek",
        source_lang: str = "ja",
        target_lang: str = "zh",
    ) -> TranslationResult:
        source_path = Path(input_path)
        if not source_path.exists():
            raise AppValidationError(f"input file does not exist: {input_path}")

        texts = [
            line
            for line in source_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return self._llm_service.translate_texts(
            texts=texts,
            provider=provider,
            output_path=output_path,
            source_lang=source_lang,
            target_lang=target_lang,
        )


_service: TranslationService | None = None
_lock = threading.Lock()


def get_translation_service() -> TranslationService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TranslationService()
    return _service
