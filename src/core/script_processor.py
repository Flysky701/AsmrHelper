"""Backward-compatibility re-export — canonical location is core/subtitles/script_processor.py."""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Importing from src.core.script_processor is deprecated. "
    "Use src.core.subtitles.script_processor instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.core.subtitles.script_processor import ScriptProcessor

__all__ = ["ScriptProcessor"]
