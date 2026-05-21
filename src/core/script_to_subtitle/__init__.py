"""Backward-compatibility re-exports — canonical locations are core/subtitles/ and core/engines/llm/."""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "Importing from src.core.script_to_subtitle is deprecated. "
    "Use src.core.subtitles (ScriptToSubtitlePipeline, ScriptToSubtitleTool) "
    "and src.core.engines.llm (LLMProcessor) instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .tool import ScriptToSubtitleTool
from .llm_processor import LLMProcessor
from .pipeline import ScriptToSubtitlePipeline

__all__ = [
    "ScriptToSubtitleTool",
    "LLMProcessor",
    "ScriptToSubtitlePipeline",
]
