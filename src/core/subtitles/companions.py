"""Conservative discovery and inspection of original-language sidecar subtitles."""
from __future__ import annotations

import math
import re
from pathlib import Path

from .loader import detect_subtitle_language
from .parser import SubtitleParser
from .text_utils import normalize_language_code


def discover_subtitles(audio_path: str | Path, *, extra_dirs=()) -> list[Path]:
    audio = Path(audio_path)
    directories = list(dict.fromkeys([audio.parent, audio.parent / "ASMR_O", *map(Path, extra_dirs)]))
    candidates = []
    for directory in directories:
        if not directory.is_dir():
            continue
        names = {child.name.casefold(): child for child in directory.iterdir() if child.is_file()}
        for suffix in (".vtt", ".srt", ".lrc"):
            for name in (audio.name + suffix, audio.stem + suffix):
                candidate = names.get(name.casefold())
                if candidate is not None and candidate not in candidates:
                    candidates.append(candidate)
    return candidates


def conservative_text_language(texts: list[str]) -> str:
    """Reject conflicting lines and tiny kana fragments embedded in translations."""
    languages = {normalize_language_code(detect_subtitle_language([part]))
                 for text in texts for part in re.split(r"[\n。！？!?]+", text) if part.strip()}
    language = next(iter(languages)) if len(languages) == 1 else "mixed"
    if language == "ja":
        text = "".join(texts)
        kana = len(re.findall(r"[\u3040-\u30ff]", text))
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        if kana / max(kana + cjk, 1) < 0.15:
            return "unknown"
    return language


def inspect_subtitle(path: str | Path) -> dict:
    """Return language evidence, never treating the filename as language evidence."""
    result = {"path": str(path), "language": "unknown", "valid": False, "reason": "", "segments": []}
    try:
        source = Path(path)
        if source.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("字幕超过 5 MB，请手动检查")
        document = SubtitleParser().parse_text(source.read_text(encoding="utf-8-sig"), source.suffix.lstrip("."))
        segments = [{"start": segment.start, "end": segment.end,
                     "text": re.sub(r"<[^>]*>", "", segment.text)} for segment in document.segments]
        if not segments:
            raise ValueError("字幕没有可用文本和时间轴")
        for entry in segments:
            start, end = float(entry["start"]), float(entry["end"])
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("字幕时间轴无效")
            if not str(entry["text"]).strip():
                raise ValueError("字幕含空文本")
        language = conservative_text_language([str(entry["text"]) for entry in segments])
        result.update(language=language, valid=True, segments=segments)
        if language in {"unknown", "mixed"}:
            result["reason"] = "字幕语言不确定或包含多种语言，不能自动当作原文"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
    return result


def subtitle_summary(path: str | Path) -> dict:
    return {key: value for key, value in inspect_subtitle(path).items() if key != "segments"}


def is_source_subtitle(inspection: dict, source_language: str) -> bool:
    expected = normalize_language_code(source_language)
    return (inspection["valid"] and not inspection["reason"] and expected not in {"auto", "unknown", "mixed"}
            and inspection["language"] == expected)
