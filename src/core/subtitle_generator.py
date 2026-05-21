"""Backward-compatibility re-export — canonical location is core/subtitles/generator.py."""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Importing from src.core.subtitle_generator is deprecated. "
    "Use src.core.subtitles.generator instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.core.subtitles.generator import SubtitleGenerator

__all__ = ["SubtitleGenerator"]
