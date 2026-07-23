"""Deprecated translation compatibility exports.

New runtime code must import translation capabilities from
``src.core.engines.llm`` and subtitle utilities from ``src.core.subtitles``.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "src.core.translate is deprecated; use src.core.engines.llm for "
    "translation and src.core.subtitles for subtitle utilities",
    DeprecationWarning,
    stacklevel=2,
)

from src.core.engines.llm.translator import Translator, translate_batch
from src.core.subtitles.loader import (
    clean_subtitle_batch,
    detect_subtitle_language,
    load_and_clean_subtitle,
    load_lrc_translations,
    load_lrc_with_timestamps,
    load_srt_translations,
    load_srt_with_timestamps,
    load_subtitle_translations,
    load_subtitle_with_timestamps,
    load_vtt_translations,
    load_vtt_with_timestamps,
)
from src.core.subtitles.text_utils import (
    deduplicate_text,
    detect_language as detect_vtt_language,
    traditional_to_simplified,
)

__all__ = [
    "Translator",
    "clean_subtitle_batch",
    "deduplicate_text",
    "detect_subtitle_language",
    "detect_vtt_language",
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
    "translate_batch",
]
