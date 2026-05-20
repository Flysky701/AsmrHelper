"""Text processing utilities for subtitles.

Provides language detection, traditional-to-simplified conversion,
and text deduplication. Migrated from src.core.translate.
"""

from __future__ import annotations

import re
from typing import List

import importlib.util as _util
import os as _os

# Direct file import to avoid circular dependency through translate/__init__.py
_tw_path = _os.path.join(_os.path.dirname(__file__), "..", "translate", "tw_zh_trad_map.py")
_spec = _util.spec_from_file_location("_tw_zh_trad_map", _tw_path)
_mod = _util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TRADITIONAL_CHARS = _mod.TRADITIONAL_CHARS
TRAD_TO_SIMP_MAP = _mod.TRAD_TO_SIMP_MAP


def detect_language(translations: List[str]) -> str:
    """Detect the primary language of subtitle text.

    Logic:
    - Pure Chinese: no kana, CJK ratio > 30%
    - Pure Japanese: has kana, no CJK
    - Mixed: both present
    - Unknown: cannot determine

    Returns: "zh_CN" | "zh_TW" | "ja" | "mixed" | "unknown"
    """
    zh_chars = 0
    ja_kana = 0
    trad_chars = 0
    total = 0

    for text in translations:
        if not text.strip():
            continue
        zh_chars += len(re.findall(r"[一-鿿]", text))
        ja_kana += len(re.findall(r"[぀-ゟ゠-ヿ]", text))
        for char in text:
            if char in TRADITIONAL_CHARS:
                trad_chars += 1
        total += len(text.strip())

    if total == 0:
        return "unknown"

    if ja_kana == 0 and zh_chars / total > 0.3:
        if trad_chars / total > 0.05:
            return "zh_TW"
        return "zh_CN"
    if ja_kana > 0 and zh_chars == 0:
        return "ja"
    if ja_kana > 0 and zh_chars > 0:
        return "mixed"

    return "unknown"


def traditional_to_simplified(text: str) -> str:
    """Convert traditional Chinese to simplified Chinese.

    Uses opencc if available, otherwise falls back to character mapping.
    """
    try:
        import opencc
        converter = opencc.OpenCC("tw2s")
        return converter.convert(text)
    except ImportError:
        result = []
        for char in text:
            result.append(TRAD_TO_SIMP_MAP.get(char, char))
        return "".join(result)


def deduplicate_text(text: str) -> str:
    """Remove consecutive duplicate words (3+ occurrences -> 1)."""
    words = text.split()
    if not words:
        return text

    result = []
    count = 1
    prev = words[0]

    for i in range(1, len(words)):
        if words[i] == prev:
            count += 1
        else:
            if count >= 3:
                result.append(prev)
            else:
                result.extend([prev] * count)
            prev = words[i]
            count = 1

    if count >= 3:
        result.append(prev)
    else:
        result.extend([prev] * count)

    return " ".join(result)
