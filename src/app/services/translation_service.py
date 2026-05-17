"""Application-layer wrapper for standalone translation workflows."""

from __future__ import annotations

import threading
from pathlib import Path

from ..dto import TranslationResult
from ..errors import AppExecutionError, AppValidationError


class TranslationService:
    """Stable application-facing facade for translation operations."""

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
        try:
            from src.core.translate import Translator

            translator = Translator(provider=provider)
            items = translator.translate_batch(
                texts,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if output_path:
            Path(output_path).write_text("\n".join(items), encoding="utf-8")

        return TranslationResult(
            items=items,
            provider=provider,
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
