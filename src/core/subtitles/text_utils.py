"""Text processing utilities for subtitles.

Provides language detection, traditional-to-simplified conversion,
and text deduplication. Migrated from src.core.translate.
"""

from __future__ import annotations

import re
from typing import List

from .tw_zh_trad_map import TRADITIONAL_CHARS, TRAD_TO_SIMP_MAP


def normalize_language_code(language: str | None) -> str:
    """Normalize supported language names and locale codes.

    Chinese locale variants intentionally collapse to ``zh`` for capability
    matching. The detector may still return ``zh_CN``/``zh_TW`` so callers
    that care about the script variant do not lose that information.
    """
    value = str(language or "").strip().lower().replace("-", "_")
    if not value:
        return "unknown"

    aliases = {
        "c": "zh",
        "chinese": "zh",
        "cmn": "zh",
        "z": "zh",
        "zh": "zh",
        "zh_cn": "zh",
        "zh_hans": "zh",
        "zh_hant": "zh",
        "zh_tw": "zh",
        "e": "en",
        "eng": "en",
        "english": "en",
        "en": "en",
        "j": "ja",
        "jp": "ja",
        "jpn": "ja",
        "japanese": "ja",
        "ja": "ja",
    }
    if value in aliases:
        return aliases[value]
    if value.startswith("zh_"):
        return "zh"
    if value.startswith("en_"):
        return "en"
    if value.startswith("ja_"):
        return "ja"
    return value


def detect_language(translations: List[str]) -> str:
    """Detect the primary language of subtitle text.

    Logic:
    - Japanese: contains kana (kanji is allowed and expected)
    - Chinese/English: choose the dominant script
    - Mixed: Chinese and Latin scripts have no clear majority
    - Unknown: cannot determine

    Returns: "zh_CN" | "zh_TW" | "ja" | "en" | "mixed" | "unknown"
    """
    zh_chars = 0
    ja_kana = 0
    latin_chars = 0
    trad_chars = 0

    for text in translations:
        if not text.strip():
            continue
        zh_chars += len(re.findall(r"[一-鿿]", text))
        ja_kana += len(re.findall(r"[぀-ゟ゠-ヿ]", text))
        latin_chars += len(re.findall(r"[A-Za-z]", text))
        for char in text:
            if char in TRADITIONAL_CHARS:
                trad_chars += 1

    meaningful_chars = zh_chars + ja_kana + latin_chars
    if meaningful_chars == 0:
        return "unknown"

    # Japanese commonly mixes kana and kanji. Treating any kanji as Chinese
    # made almost every natural Japanese subtitle appear as ``mixed``.
    if ja_kana > 0:
        return "ja"

    if zh_chars > 0 and latin_chars > 0:
        zh_ratio = zh_chars / (zh_chars + latin_chars)
        if 0.4 <= zh_ratio <= 0.6:
            return "mixed"
        if zh_ratio < 0.4:
            return "en"

    if zh_chars > 0:
        if trad_chars / zh_chars > 0.05:
            return "zh_TW"
        return "zh_CN"

    if latin_chars > 0:
        return "en"

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
