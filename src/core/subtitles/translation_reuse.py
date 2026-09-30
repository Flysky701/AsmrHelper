"""Conservative, language-bound reuse of translations without changing source files."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import hashlib
import math
import re
from pathlib import Path

from .companions import conservative_text_language, discover_subtitles, inspect_subtitle, is_source_subtitle
from .parser import SubtitleParser
from .text_utils import normalize_language_code


def reuse_enabled(options: dict) -> bool:
    value = options.get("reuse_existing", True)
    if not isinstance(value, bool):
        raise ValueError("复用已有译文选项必须为布尔值")
    return value


def timing_key(segment: dict) -> tuple[int, int] | None:
    try:
        start, end = float(segment["start"]), float(segment["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            return None
        return round(start * 1000), round(end * 1000)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def audio_duration(input_path: str) -> float | None:
    try:
        import soundfile as sf
        duration = float(sf.info(input_path).duration)
        return duration if math.isfinite(duration) and duration > 0 else None
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def subtitle_candidates(input_path: str, paths=None) -> list[str]:
    return list(dict.fromkeys(map(str, paths or discover_subtitles(input_path))))


def usable_subtitles(paths: list[str], language: str, duration: float | None, *, partial=False):
    expected = normalize_language_code(language)
    if duration is None or expected not in {"ja", "zh", "en"}:
        return []
    usable = []
    for path in paths:
        if Path(path).suffix.lower() not in {".srt", ".vtt", ".lrc"}:
            continue
        if partial:
            # Empty or wrong-language cues remain gaps; never shift later translations.
            try:
                source = Path(path)
                if source.stat().st_size > 5 * 1024 * 1024:
                    continue
                document = SubtitleParser().parse_text(source.read_text(encoding="utf-8-sig"), source.suffix[1:])
                entries = []
                counts = Counter(timing_key({"start": s.start, "end": s.end}) for s in document.segments)
                for segment in document.segments:
                    text = re.sub(r"<[^>]*>", "", segment.text).strip()
                    entry = {"start": segment.start, "end": segment.end, "text": text}
                    if (text and timing_key(entry) is not None and counts[timing_key(entry)] == 1
                            and segment.end <= duration + 0.1
                            and conservative_text_language([text]) == expected):
                        entries.append(entry)
                if entries:
                    usable.append({"path": path, "segments": entries})
            except (OSError, ValueError, TypeError):
                pass
            continue
        inspection = inspect_subtitle(path)
        if (is_source_subtitle(inspection, expected)
                and all(float(s["end"]) <= duration + 0.1 for s in inspection["segments"])):
            usable.append(inspection)
    return usable


def match_translations(segments: list[dict], candidates: list[dict]) -> list[str]:
    """Match unique millisecond intervals; conflicting or duplicate cues are not evidence."""
    source_keys = [timing_key(segment) for segment in segments]
    source_counts = Counter(source_keys)
    by_time: dict[tuple[int, int], set[str]] = {}
    ambiguous = set()
    for candidate in candidates:
        keys = [timing_key(s) for s in candidate["segments"]]
        counts = Counter(keys)
        for segment, key in zip(candidate["segments"], keys, strict=True):
            if key is None:
                continue
            if counts[key] > 1:
                ambiguous.add(key)
            text = str(segment.get("text", "")).strip()
            if text:
                by_time.setdefault(key, set()).add(text)
    result = []
    for key in source_keys:
        texts = by_time.get(key, set())
        result.append(next(iter(texts)) if key is not None and source_counts[key] == 1
                      and key not in ambiguous and len(texts) == 1 else "")
    return result


def reusable_translations(segments, paths, source_lang, target_lang, input_path):
    if normalize_language_code(source_lang) == normalize_language_code(target_lang):
        return [""] * len(segments)
    candidates = usable_subtitles(paths, target_lang, audio_duration(input_path), partial=True)
    anchored = [s["translation_source_anchor"] if isinstance(s.get("translation_source_anchor"), dict)
                and s["translation_source_anchor"].get("text") == s.get("text") else s for s in segments]
    return match_translations(anchored, candidates)


def direct_subtitle_input(profile: dict, input_path: str, paths=None) -> dict:
    """Validate a target-only timeline before any engine is probed or executed."""
    options = profile["stages"]["translate"].get("options", {})
    target = normalize_language_code(profile.get("target_lang", "zh"))
    source = normalize_language_code(profile.get("source_lang", "ja"))
    duration = audio_duration(input_path)
    if duration is None:
        raise ValueError("直接配音无法验证音频时长，请检查输入音频")
    candidates = subtitle_candidates(input_path, paths or options.get("reuse_companion_paths"))
    targets, reasons = [], []
    for path in candidates:
        inspection = inspect_subtitle(path)
        if inspection["language"] != target or not inspection["valid"] or inspection["reason"]:
            reasons.append(inspection["reason"] or "字幕语言与目标语言不一致")
            continue
        subtitle = Path(path)
        # LRC end times are inferred by the parser; direct synthesis requires explicit intervals.
        if subtitle.suffix.lower() not in {".srt", ".vtt"}:
            reasons.append("直接配音需要带明确起止时间的 SRT 或 VTT 字幕")
            continue
        raw = subtitle.read_bytes()
        entries = inspection["segments"]
        blocks = re.split(r"\n\s*\n", raw.decode("utf-8-sig").replace("\r\n", "\n").strip())
        if subtitle.suffix.lower() == ".vtt":
            blocks = [block for block in blocks if block.split(maxsplit=1)[0].upper()
                      not in {"WEBVTT", "NOTE", "STYLE", "REGION"}]
        cue_count = len(blocks)
        keys = [timing_key(entry) for entry in entries]
        if (cue_count != len(entries) or len(set(keys)) != len(keys)
                or any(sum("-->" in line for line in block.splitlines()[:2]) != 1 for block in blocks)):
            reasons.append("字幕包含空白、无法解析或重复的条目，请补齐后直接配音")
            continue
        if (None in keys or keys != sorted(keys)
                or any(float(entry["end"]) > duration + 0.1 for entry in entries)):
            reasons.append("字幕时间轴无效、顺序错误或超出音频时长，请先校准")
            continue
        targets.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "segments": entries})
    if not targets:
        detail = "；".join(dict.fromkeys(reasons)) or "未找到带时间轴和目标语言证据的字幕"
        raise ValueError(f"无法直接配音：{detail}。请补充目标字幕，或切回原流程识别／翻译")
    signatures = {tuple((timing_key(s), s["text"]) for s in item["segments"]) for item in targets}
    if len(signatures) > 1:
        raise ValueError("存在多个不同的目标字幕，无法确定直接配音内容；请保留一个明确版本")
    selected = targets[0]
    if options.get("direct_subtitle_sha256") and (
            selected["sha256"] != options["direct_subtitle_sha256"]
            or selected["path"] != options.get("direct_subtitle_path")):
        raise ValueError("直接配音字幕已改变，请检查后重新提交任务")
    originals = usable_subtitles(candidates, source, duration) if source != target else []
    for original in originals:
        if not all(match_translations(original["segments"], [selected])):
            raise ValueError("目标字幕缺少对应原文条目，不能完整直接配音；请补齐译文或切回原流程补译")
    original_texts = match_translations(selected["segments"], originals)
    selected["segments"] = [
        {"start": entry["start"], "end": entry["end"], "text": original,
         "translation": entry["text"].strip(), "translation_lang": profile.get("target_lang", "zh")}
        for entry, original in zip(selected["segments"], original_texts, strict=True)
    ]
    selected["candidates"] = candidates
    return selected


def prepare_translation_profile(profile: dict, input_path: str | None, paths=None, *, allow_unverified=False) -> dict:
    """Remove translation dependencies when all cues can be reused.

    The reuse-only marker is always revalidated, including on queued execution.
    A changed file fails closed instead of silently issuing a paid translation.
    With no working connection, valid target cues may be checked against future
    ASR results. That conditional mode must stop if any cue still needs translation.
    """
    if profile.get("workflow") is not None:
        from src.core.orchestration.pipeline.workflow import prepare_workflow
        return prepare_workflow(profile, input_path, paths)
    # Read compatibility for historical task profiles. New workbench requests
    # always carry explicit workflow bindings; these old switches cannot affect them.
    stages = profile.get("stages")
    if not isinstance(stages, dict):
        return profile
    stage = stages.get("translate", {})
    if not isinstance(stage, dict):
        return profile
    options = stage.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("翻译选项必须为对象")
    if options.get("direct_tts") is True:
        if not reuse_enabled(options) or not stages.get("tts", {}).get("enabled", True):
            raise ValueError("直接配音需要启用已有字幕复用和 TTS")
        if not input_path:
            raise ValueError("直接配音需要先选择音频及其目标字幕")
        selected = direct_subtitle_input(profile, input_path, paths)
        result = deepcopy(profile)
        for name in ("separate", "asr", "align", "translate", "mix"):
            result["stages"].setdefault(name, {})["enabled"] = False
        result["stages"]["translate"].setdefault("options", {}).update(
            reuse_only=False, reuse_unverified=False,
            direct_subtitle_path=selected["path"], direct_subtitle_sha256=selected["sha256"],
            reuse_companion_paths=selected["candidates"],
        )
        return result
    only = options.get("reuse_only") is True
    unverified = options.get("reuse_unverified") is True
    if not stage or not (stage.get("enabled", True) or only):
        return profile
    enabled = reuse_enabled(options)
    source, target = profile.get("source_lang", "ja"), profile.get("target_lang", "zh")
    full = False
    targets = []
    candidates = []
    if enabled and input_path and source != target:
        candidates = subtitle_candidates(input_path, paths or options.get("reuse_companion_paths"))
        duration = audio_duration(input_path)
        targets = usable_subtitles(candidates, target, duration, partial=True)
        originals = usable_subtitles(candidates, source, duration)
        stages = profile.get("stages", {})
        if originals and stages.get("asr", {}).get("enabled", True):
            originals = originals[0]["segments"]
            translations = match_translations(originals, targets)
            full = bool(originals) and all(translations)
    conditional = bool(targets) and (allow_unverified or (only and unverified))
    if only and not (full or conditional):
        raise ValueError("已确认复用的译文或原文已改变，无法完整匹配；请检查字幕并重新提交任务")
    if not full and not conditional and not candidates:
        return profile
    result = deepcopy(profile)
    result["stages"]["translate"].setdefault("options", {})["reuse_companion_paths"] = candidates
    if not (full or conditional):
        return result
    result["stages"]["translate"]["enabled"] = False
    result["stages"]["translate"].setdefault("options", {}).update(
        reuse_only=True, reuse_unverified=not full,
    )
    return result


def cached_translations(path: Path, segments, source_lang, target_lang) -> list[str]:
    """Only structured records carrying language and exact original text can be reused."""
    empty = [""] * len(segments)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("version") != 1 or data.get("source_lang") != source_lang
                or data.get("target_lang") != target_lang):
            return empty
        entries = data["segments"]
        if not isinstance(entries, list):
            return empty
        indexed = {}
        for entry in entries:
            if not isinstance(entry, dict):
                return empty
            key = (timing_key(entry), entry.get("source_text"))
            if key in indexed:
                return empty
            indexed[key] = entry.get("translation")
        counts = Counter((timing_key(s), s.get("text", "")) for s in segments)
        return [value.strip() if isinstance(value := indexed.get((timing_key(s), s.get("text", ""))), str)
                and timing_key(s) is not None and counts[(timing_key(s), s.get("text", ""))] == 1
                else "" for s in segments]
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return empty


def unused_output(directory: Path, name: str) -> Path:
    """Keep imported, cached and manually edited output bytes intact."""
    path = directory / name
    counter = 2
    while path.exists():
        path = directory / f"{Path(name).stem}.{counter}{Path(name).suffix}"
        counter += 1
    return path
