"""Core subtitle domain exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CleanerConfig",
    "SoundEffectPatterns",
    "SubtitleAsset",
    "SubtitleCleaner",
    "SubtitleDocument",
    "SubtitleDomainService",
    "SubtitleExporter",
    "SubtitleFormatValidator",
    "SubtitleNormalizer",
    "SubtitleParser",
    "SubtitleSegment",
    "clean_subtitle_batch",
    "clean_subtitle_text",
]

_EXPORTS = {
    "CleanerConfig": ("src.core.subtitles.cleaner", "CleanerConfig"),
    "SoundEffectPatterns": ("src.core.subtitles.cleaner", "SoundEffectPatterns"),
    "SubtitleAsset": ("src.core.subtitles.models", "SubtitleAsset"),
    "SubtitleCleaner": ("src.core.subtitles.cleaner", "SubtitleCleaner"),
    "SubtitleDocument": ("src.core.subtitles.models", "SubtitleDocument"),
    "SubtitleDomainService": ("src.core.subtitles.service", "SubtitleDomainService"),
    "SubtitleExporter": ("src.core.subtitles.exporter", "SubtitleExporter"),
    "SubtitleFormatValidator": ("src.core.subtitles.cleaner", "SubtitleFormatValidator"),
    "SubtitleNormalizer": ("src.core.subtitles.normalizer", "SubtitleNormalizer"),
    "SubtitleParser": ("src.core.subtitles.parser", "SubtitleParser"),
    "SubtitleSegment": ("src.core.subtitles.models", "SubtitleSegment"),
    "clean_subtitle_batch": ("src.core.subtitles.cleaner", "clean_subtitle_batch"),
    "clean_subtitle_text": ("src.core.subtitles.cleaner", "clean_subtitle_text"),
}


def __getattr__(name: str):
    try:
        module_name, export_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), export_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
