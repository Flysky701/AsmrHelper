"""Subtitle file loading, format detection, and text processing utilities.

Migrated from src.core.translate to consolidate subtitle logic
under the core/subtitles domain.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List


# ===== Timestamp parsers =====

def _parse_vtt_time(time_str: str) -> float:
    """Convert VTT timestamp '00:00:24.140' or '00:24.140' to seconds."""
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")

    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)

    return 0.0


def _parse_srt_time(time_str: str) -> float:
    """Convert SRT timestamp '00:00:01,000' to seconds."""
    time_str = time_str.strip()
    parts = time_str.replace(",", ".").split(":")

    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)

    return 0.0


# ===== VTT loaders =====

def load_vtt_translations(vtt_path: str) -> List[str]:
    """Load translation text from a VTT file (plain text list)."""
    translations: List[str] = []

    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        # Skip WEBVTT header
        while i < len(lines) and "WEBVTT" not in lines[i]:
            i += 1
        i += 1

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.isdigit():
                i += 1
                continue

            if "-->" in line:
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                if text_lines:
                    translations.append(" ".join(text_lines))
                continue

            i += 1

        print(f"[VTT Loader] 加载了 {len(translations)} 条翻译: {vtt_path}")

    except FileNotFoundError:
        print(f"[VTT Loader] 文件不存在: {vtt_path}")
    except Exception as e:
        print(f"[VTT Loader] 解析失败: {e}")

    return translations


def load_vtt_with_timestamps(vtt_path: str) -> List[dict]:
    """Load VTT entries with timestamps: [{start, end, text}, ...]."""
    entries: List[dict] = []

    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        while i < len(lines) and "WEBVTT" not in lines[i]:
            i += 1
        i += 1

        while i < len(lines):
            line = lines[i].strip()

            if not line or line.isdigit():
                i += 1
                continue

            if "-->" in line:
                parts = line.split("-->")
                start_str = parts[0].strip()
                end_str = parts[1].strip().split()[0]
                start_sec = _parse_vtt_time(start_str)
                end_sec = _parse_vtt_time(end_str)

                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                if text_lines:
                    entries.append({
                        "start": start_sec,
                        "end": end_sec,
                        "text": " ".join(text_lines),
                    })
                continue

            i += 1

        print(f"[VTT Loader] 加载了 {len(entries)} 条带时间戳翻译: {vtt_path}")

    except Exception as e:
        print(f"[VTT Loader] 解析失败: {e}")

    return entries


# ===== SRT loaders =====

def load_srt_translations(srt_path: str) -> List[str]:
    """Load translation text from an SRT file (plain text list)."""
    translations: List[str] = []

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            if line.isdigit():
                i += 1
                continue

            if "-->" in line:
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                if text_lines:
                    translations.append(" ".join(text_lines))
                continue

            i += 1

        print(f"[SRT Loader] 加载了 {len(translations)} 条翻译: {srt_path}")

    except FileNotFoundError:
        print(f"[SRT Loader] 文件不存在: {srt_path}")
    except Exception as e:
        print(f"[SRT Loader] 解析失败: {e}")

    return translations


def load_srt_with_timestamps(srt_path: str) -> List[dict]:
    """Load SRT entries with timestamps: [{start, end, text}, ...]."""
    entries: List[dict] = []

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                i += 1
                continue

            if line.isdigit():
                i += 1
                continue

            if "-->" in line:
                parts = line.split("-->")
                start_str = parts[0].strip()
                end_str = parts[1].strip().split()[0]
                start_sec = _parse_srt_time(start_str)
                end_sec = _parse_srt_time(end_str)

                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                if text_lines:
                    entries.append({
                        "start": start_sec,
                        "end": end_sec,
                        "text": " ".join(text_lines),
                    })
                continue

            i += 1

        print(f"[SRT Loader] 加载了 {len(entries)} 条带时间戳翻译: {srt_path}")

    except Exception as e:
        print(f"[SRT Loader] 解析失败: {e}")

    return entries


# ===== LRC loaders =====

def load_lrc_translations(lrc_path: str) -> List[str]:
    """Load translation text from an LRC file (plain text list)."""
    translations: List[str] = []

    try:
        with open(lrc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            match = re.match(r"\[(\d{2}):(\d{2})[.:](\d{2})\](.+)", line)
            if match:
                text = match.group(4).strip()
                if text:
                    translations.append(text)

        print(f"[LRC Loader] 加载了 {len(translations)} 条翻译: {lrc_path}")

    except FileNotFoundError:
        print(f"[LRC Loader] 文件不存在: {lrc_path}")
    except Exception as e:
        print(f"[LRC Loader] 解析失败: {e}")

    return translations


def load_lrc_with_timestamps(lrc_path: str) -> List[dict]:
    """Load LRC entries with timestamps: [{start, end, text}, ...]."""
    entries: List[dict] = []

    try:
        with open(lrc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()
            match = re.match(r"\[(\d{2}):(\d{2})[.:](\d{2})\](.+)", line)
            if match:
                mm = int(match.group(1))
                ss = int(match.group(2))
                xx = int(match.group(3))
                text = match.group(4).strip()

                if text:
                    start_sec = mm * 60 + ss + xx / 100.0
                    entries.append({
                        "start": start_sec,
                        "end": start_sec + 3.0,  # default, corrected below
                        "text": text,
                    })

        # Fix end_sec: use next entry's start as current entry's end
        for i in range(len(entries)):
            if i + 1 < len(entries):
                next_start = entries[i + 1]["start"]
                if next_start > entries[i]["start"]:
                    entries[i]["end"] = next_start
            else:
                entries[i]["end"] = entries[i]["start"] + 3.0

        print(f"[LRC Loader] 加载了 {len(entries)} 条带时间戳翻译: {lrc_path}")

    except Exception as e:
        print(f"[LRC Loader] 解析失败: {e}")

    return entries


# ===== Unified loaders =====

def load_subtitle_translations(subtitle_path: str) -> List[str]:
    """Load subtitle text with auto format detection (.vtt, .srt, .lrc)."""
    ext = Path(subtitle_path).suffix.lower()

    if ext == ".vtt":
        return load_vtt_translations(subtitle_path)
    elif ext == ".srt":
        return load_srt_translations(subtitle_path)
    elif ext == ".lrc":
        return load_lrc_translations(subtitle_path)
    else:
        try:
            with open(subtitle_path, "r", encoding="utf-8") as f:
                content = f.read(1024)
            if "WEBVTT" in content:
                return load_vtt_translations(subtitle_path)
            elif "-->" in content:
                return load_srt_translations(subtitle_path)
            elif re.search(r'\[\d{2}:\d{2}', content):
                return load_lrc_translations(subtitle_path)
        except Exception:
            pass

        print(f"[Subtitle Loader] 不支持的字幕格式: {subtitle_path}")
        return []


def load_subtitle_with_timestamps(subtitle_path: str) -> List[dict]:
    """Load subtitle entries with timestamps and auto format detection."""
    ext = Path(subtitle_path).suffix.lower()

    if ext == ".vtt":
        return load_vtt_with_timestamps(subtitle_path)
    elif ext == ".srt":
        return load_srt_with_timestamps(subtitle_path)
    elif ext == ".lrc":
        return load_lrc_with_timestamps(subtitle_path)
    else:
        try:
            with open(subtitle_path, "r", encoding="utf-8") as f:
                content = f.read(1024)
            if "WEBVTT" in content:
                return load_vtt_with_timestamps(subtitle_path)
            elif "-->" in content:
                return load_srt_with_timestamps(subtitle_path)
            elif re.search(r'\[\d{2}:\d{2}', content):
                return load_lrc_with_timestamps(subtitle_path)
        except Exception:
            pass

        print(f"[Subtitle Loader] 不支持的字幕格式: {subtitle_path}")
        return []


# ===== Language detection =====

def detect_subtitle_language(translations: List[str]) -> str:
    """Detect the primary language of subtitle text.

    Returns: "zh_CN" | "zh_TW" | "ja" | "mixed" | "unknown"
    """
    from .text_utils import detect_language
    return detect_language(translations)


# ===== Text processing (delegated to text_utils) =====

def traditional_to_simplified(text: str) -> str:
    """Convert traditional Chinese to simplified Chinese."""
    from .text_utils import traditional_to_simplified as _t2s
    return _t2s(text)


def deduplicate_text(text: str) -> str:
    """Remove consecutive duplicate words (3+ occurrences -> 1)."""
    from .text_utils import deduplicate_text as _dedup
    return _dedup(text)


# ===== Cleaning integration =====

def load_and_clean_subtitle(
    subtitle_path: str,
    clean_sound_effects: bool = True,
    clean_speaker_names: bool = True,
) -> List[dict]:
    """Load subtitle and clean sound effects / speaker names.

    Returns: [{start, end, text, original_text?}, ...]
    """
    try:
        from src.core.subtitles.cleaner import CleanerConfig, SubtitleCleaner
    except ImportError:
        print("[WARN] 字幕清理模块不可用，返回原始字幕")
        return load_subtitle_with_timestamps(subtitle_path)

    entries = load_subtitle_with_timestamps(subtitle_path)
    if not entries:
        return []

    config = CleanerConfig(
        remove_sound_effects=clean_sound_effects,
        remove_speaker_names=clean_speaker_names,
        remove_punctuation_only=True,
    )
    cleaner = SubtitleCleaner(config)

    cleaned_entries = []
    stats = {"total": 0, "changed": 0, "removed": 0}

    for entry in entries:
        stats["total"] += 1
        original_text = entry.get("text", "")

        if not original_text.strip():
            continue

        cleaned_text = cleaner.clean(original_text)

        if cleaned_text.strip():
            entry_cleaned = entry.copy()
            entry_cleaned["text"] = cleaned_text
            if cleaned_text != original_text:
                entry_cleaned["original_text"] = original_text
            cleaned_entries.append(entry_cleaned)
            stats["changed"] += 1
        else:
            stats["removed"] += 1

    if stats["changed"] > 0 or stats["removed"] > 0:
        print(f"[SubtitleCleaner] 清理完成: {stats['changed']} 条修改, {stats['removed']} 条删除")

    return cleaned_entries


def clean_subtitle_batch(
    texts: List[str],
    clean_sound_effects: bool = True,
    clean_speaker_names: bool = True,
) -> List[str]:
    """Batch clean subtitle text."""
    try:
        from src.core.subtitles.cleaner import CleanerConfig, SubtitleCleaner
    except ImportError:
        return texts

    config = CleanerConfig(
        remove_sound_effects=clean_sound_effects,
        remove_speaker_names=clean_speaker_names,
    )
    cleaner = SubtitleCleaner(config)
    return cleaner.clean_batch(texts)
