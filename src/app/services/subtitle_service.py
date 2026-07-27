"""Subtitle application service backed by the core subtitle domain."""

from __future__ import annotations

import threading
from pathlib import Path

from src.core.subtitles import SubtitleDomainService

from ..dto import (
    SubtitleAsset,
    SubtitleDocument,
    SubtitleSegment,
    SubtitleTranslationResult,
)
from ..errors import AppExecutionError, AppValidationError


class SubtitleService:
    """Wrap the core subtitle domain with application-layer errors."""

    def __init__(self) -> None:
        self._domain = SubtitleDomainService()

    def from_timestamp_entries(self, entries: list[dict]) -> SubtitleDocument:
        return self._domain.from_timestamp_entries(entries)

    def to_timestamp_entries(self, document: SubtitleDocument) -> list[dict]:
        return self._domain.to_timestamp_entries(document)

    def parse_text(self, content: str, fmt: str = "srt") -> SubtitleDocument:
        try:
            return self._domain.parse_text(content, fmt)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def load_asset(self, file_path: str) -> SubtitleAsset:
        try:
            return self._domain.load_asset(file_path)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except OSError as exc:
            raise AppExecutionError(f"failed to read subtitle file: {file_path}: {exc}") from exc

    def create_asset(
        self,
        *,
        document: SubtitleDocument,
        fmt: str = "srt",
        source_path: str = "",
        warnings: list[str] | None = None,
    ) -> SubtitleAsset:
        return self._domain.create_asset(
            document=document,
            fmt=fmt,
            source_path=source_path,
            warnings=warnings,
        )

    def get_asset(self, asset_id: str) -> SubtitleAsset:
        try:
            return self._domain.get_asset(asset_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def normalize_document(self, document: SubtitleDocument) -> SubtitleDocument:
        return self._domain.normalize_document(document)

    def export_srt_text(self, document: SubtitleDocument) -> str:
        return self._domain.export_srt_text(document)

    def export_bilingual_srt_text(self, segments: list[dict]) -> str:
        return self._domain.export_bilingual_srt_text(segments)

    def export_bilingual_vtt_text(self, segments: list[dict]) -> str:
        return self._domain.export_bilingual_vtt_text(segments)

    def export_bilingual_subtitle(
        self,
        segments: list[dict],
        output_path: str,
        bilingual: bool = True,
    ) -> str:
        try:
            return self._domain.export_bilingual_subtitle(
                segments,
                output_path,
                bilingual=bilingual,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except OSError as exc:
            raise AppExecutionError(f"failed to write subtitle file: {output_path}: {exc}") from exc

    def export_document(
        self,
        document: SubtitleDocument,
        *,
        output_path: str,
        fmt: str | None = None,
    ) -> str:
        try:
            return self._domain.export_document(document, output_path=output_path, fmt=fmt)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except OSError as exc:
            raise AppExecutionError(f"failed to write subtitle file: {output_path}: {exc}") from exc

    def translate_subtitle(
        self,
        *,
        input_path: str,
        output_path: str = "",
        provider: str = "deepseek",
        source_lang: str = "ja",
        target_lang: str = "zh",
        bilingual: bool = True,
    ) -> SubtitleTranslationResult:
        from src.core.subtitles import load_and_clean_subtitle
        from src.core.engines.llm import LlmOperationRuntime

        source = Path(input_path)
        if not source.exists():
            raise AppValidationError(f"subtitle file does not exist: {input_path}")

        try:
            entries = load_and_clean_subtitle(str(source))
            if not entries:
                raise AppValidationError("subtitle file contains no entries")

            source_label = self._map_language(source_lang)
            target_label = self._map_language(target_lang)
            runtime = LlmOperationRuntime()
            translations = runtime.translate_texts(
                texts=[str(entry.get("text", "")) for entry in entries],
                profile={
                    "provider": provider,
                    "model": "",
                    "common_options": {},
                    "provider_options": {},
                },
                source_lang=source_label,
                target_lang=target_label,
            )
            segments = [
                {
                    **entry,
                    "translation": translations[index] if index < len(translations) else "",
                }
                for index, entry in enumerate(entries)
            ]
        except AppValidationError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        resolved_output = output_path or str(source.with_stem(source.stem + f"_{target_lang}"))
        try:
            self.export_bilingual_subtitle(segments, resolved_output, bilingual)
        except Exception as exc:
            raise AppExecutionError(f"failed to write output subtitle: {exc}") from exc

        return SubtitleTranslationResult(
            input_path=input_path,
            output_path=resolved_output,
            total_segments=len(segments),
            provider=provider,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def bilingualize_segments(
        self,
        *,
        segments: list[dict],
        output_path: str,
    ) -> str:
        try:
            return self.export_bilingual_subtitle(segments, output_path, True)
        except AppValidationError:
            raise
        except Exception as exc:
            raise AppExecutionError(f"failed to write bilingual subtitle: {exc}") from exc

    @staticmethod
    def _map_language(language: str) -> str:
        mapping = {
            "ja": "日文",
            "zh": "中文",
            "en": "英文",
        }
        return mapping.get(language, language)


_service: SubtitleService | None = None
_lock = threading.Lock()


def get_subtitle_service() -> SubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SubtitleService()
    return _service
