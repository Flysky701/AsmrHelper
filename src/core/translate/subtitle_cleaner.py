"""Backward-compatibility re-export — canonical location is core/subtitles/cleaner.py."""

from __future__ import annotations

from src.core.subtitles.cleaner import (
    CleanerConfig,
    SoundEffectPatterns,
    SubtitleCleaner,
    SubtitleFormatValidator,
    clean_subtitle_batch,
    clean_subtitle_text,
)

__all__ = [
    "CleanerConfig",
    "SoundEffectPatterns",
    "SubtitleCleaner",
    "SubtitleFormatValidator",
    "clean_subtitle_batch",
    "clean_subtitle_text",
]
