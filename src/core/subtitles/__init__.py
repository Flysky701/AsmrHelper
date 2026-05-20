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
    "deduplicate_text",
    "detect_subtitle_language",
    "load_and_clean_subtitle",
    "load_lrc_translations",
    "load_lrc_with_timestamps",
    "load_srt_translations",
    "load_srt_with_timestamps",
    "load_subtitle_translations",
    "load_subtitle_with_timestamps",
    "load_vtt_translations",
    "load_vtt_with_timestamps",
    "traditional_to_simplified",
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
    "clean_subtitle_batch": ("src.core.subtitles.loader", "clean_subtitle_batch"),
    "clean_subtitle_text": ("src.core.subtitles.cleaner", "clean_subtitle_text"),
    "deduplicate_text": ("src.core.subtitles.text_utils", "deduplicate_text"),
    "detect_subtitle_language": ("src.core.subtitles.loader", "detect_subtitle_language"),
    "load_and_clean_subtitle": ("src.core.subtitles.loader", "load_and_clean_subtitle"),
    "load_lrc_translations": ("src.core.subtitles.loader", "load_lrc_translations"),
    "load_lrc_with_timestamps": ("src.core.subtitles.loader", "load_lrc_with_timestamps"),
    "load_srt_translations": ("src.core.subtitles.loader", "load_srt_translations"),
    "load_srt_with_timestamps": ("src.core.subtitles.loader", "load_srt_with_timestamps"),
    "load_subtitle_translations": ("src.core.subtitles.loader", "load_subtitle_translations"),
    "load_subtitle_with_timestamps": ("src.core.subtitles.loader", "load_subtitle_with_timestamps"),
    "load_vtt_translations": ("src.core.subtitles.loader", "load_vtt_translations"),
    "load_vtt_with_timestamps": ("src.core.subtitles.loader", "load_vtt_with_timestamps"),
    "traditional_to_simplified": ("src.core.subtitles.text_utils", "traditional_to_simplified"),
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
