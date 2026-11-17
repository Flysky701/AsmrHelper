"""Two-phase DraftSession orchestration service (`PREPARE -> AWAITING_REVIEW -> COMMIT`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any
from uuid import uuid4

import numpy as np
import soundfile as sf

from src.app.errors import AppExecutionError, AppValidationError
from src.app.persistence.draft_store import DraftConflictError, DraftStore, get_draft_store
from src.core.speech.compiler import compile_recipe
from src.core.speech.store import SpeechStore, build_plan
from src.core.subtitles.exporter import SubtitleExporter
from src.core.subtitles.loader import detect_subtitle_language
from src.core.subtitles.models import SubtitleDocument, SubtitleSegment as DomainSubtitleSegment
from src.core.subtitles.parser import SubtitleParser
from src.core.subtitles.text_utils import normalize_language_code
from src.mixer import Mixer
from src.utils import get_ffmpeg, sanitize_filename


AUDIO_EXTENSIONS = (".wav", ".flac", ".m4a", ".ogg", ".mp3")
SUBTITLE_EXTENSIONS = (".srt", ".vtt", ".lrc")
SCRIPT_EXTENSIONS = (".txt", ".pdf")

_SKIP_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    ".runtimes",
    "node_modules",
    "by_product",
    "_draft_staging",
    "drafts",
    "speech",
    "aligned",
    "assemblies",
})

_FORMAT_PRIORITY = {
    ".wav": 0,
    ".flac": 1,
    ".m4a": 2,
    ".ogg": 3,
    ".mp3": 4,
}

# Hiragana (ぁ..ゖ) and Katakana (ァ..ヺ), excluding prolonged sound mark ー and wave dash 〜
_KANA_SYLLABLE_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
# Meaningful speech characters: CJK Unified Ideographs, Hiragana/Katakana, Hangul, or word alphanumerics
_SPEECH_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z0-9]")
# Punctuation, whitespace, and musical/ASMR decorative symbols ignored when estimating spoken char count
_NON_SPOKEN_RE = re.compile(
    r"[\s，。！？；：、“”‘’（）【】《》〈〉「」『』,.!?;:\"'()\[\]{}<>…—～~·・♪♫♥♡★☆_\-+=/\\|]+"
)

_CONTAINER_DIR_MARKERS = {
    "wav": "main",
    "flac": "main",
    "mp3": "main",
    "m4a": "main",
    "ogg": "main",
    "audio": "main",
    "tracks": "main",
    "seあり": "main",
    "効果音あり": "main",
    "with_se": "main",
    "with-se": "main",
    "seなし": "no_se",
    "効果音なし": "no_se",
    "bgmなし": "no_se",
    "no_se": "no_se",
    "no-se": "no_se",
    "nose": "no_se",
    "without_se": "no_se",
    "without-se": "no_se",
    "无音效": "no_se",
    "vocals": "vocals",
    "vocal": "vocals",
    "干声": "vocals",
    "人声": "vocals",
    "se_only": "se_only",
    "se-only": "se_only",
    "inst": "se_only",
    "instrumental": "se_only",
    "off_vocal": "se_only",
    "伴奏": "se_only",
    "环境音": "se_only",
    "subtitles": "subtitles",
    "subs": "subtitles",
    "字幕": "subtitles",
    "scripts": "scripts",
    "script": "scripts",
    "台本": "scripts",
}

_STEM_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vocals",
        re.compile(
            r"(?:[_\-\s(\[（【]+)(?:vocals?|vocal[_\-\s]?only|dry[_\-\s]?vocals?|人声|干声)(?:[)\]）】]*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "no_se",
        re.compile(
            r"(?:[_\-\s(\[（【]*)(?:no[_\-\s]?se|without[_\-\s]?se|se[_\-\s]?off|seなし|効果音なし|bgmなし|无音效)(?:[)\]）】]*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "se_only",
        re.compile(
            r"(?:[_\-\s(\[（【]+)(?:se[_\-\s]?only|bgm[_\-\s]?only|inst(?:rumental)?|off[_\-\s]?vocal|no[_\-\s]?vocals?|无人声|伴奏|环境音)(?:[)\]）】]*)$",
            re.IGNORECASE,
        ),
    ),
    (
        "main",
        re.compile(
            r"(?:[_\-\s(\[（【]*)(?:with[_\-\s]?se|se[_\-\s]?on|seあり|効果音あり|有音效)(?:[)\]）】]*)$",
            re.IGNORECASE,
        ),
    ),
)

_LANG_SUFFIX_RE = re.compile(
    r"(?:[._\-])(?:ja|jp|jpn|zh|chs|cht|sc|tc|zh[_\-]?cn|zh[_\-]?tw|en|bilingual|双语)$",
    re.IGNORECASE,
)
_SCRIPT_SUFFIX_RE = re.compile(
    r"(?:[_\-\s(\[（【]*)(?:script|transcript|台本|剧本)(?:[)\]）】]*)$",
    re.IGNORECASE,
)
_TRACK_NUMBER_RE = re.compile(r"^(?:track|tr|轨|音轨)?[_\-\s]*0*(\d{1,3})(?:[_\-\s.]+|$)", re.IGNORECASE)


def has_speech_text(text: str) -> bool:
    """Return True when `text` contains speakable letters, kana, or CJK characters."""
    if not text or not text.strip():
        return False
    return bool(_SPEECH_CHAR_RE.search(text))


def count_spoken_units(text: str) -> int:
    """Count effective spoken characters/words for deterministic Chinese TTS duration estimation."""
    cleaned = _NON_SPOKEN_RE.sub("", text or "")
    if not cleaned:
        return 0
    cjk_or_kana = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", cleaned))
    remainder = re.sub(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", " ", cleaned)
    ascii_words = [token for token in remainder.split() if token]
    word_units = sum(max(1, math.ceil(len(word) / 3)) for word in ascii_words)
    return cjk_or_kana + word_units


def has_japanese_residue(text: str) -> bool:
    """Return True if target text still contains Japanese Hiragana/Katakana syllables."""
    if not text:
        return False
    return bool(_KANA_SYLLABLE_RE.search(text))


def _normalize_stem_and_role(path: Path, root_dir: Path) -> tuple[str, str, int | None]:
    """Derive canonical stem key, track role (`main`/`vocals`/`no_se`/`se_only`), and optional track number."""
    stem = path.stem
    # Handle double extensions like `track01.wav.vtt` or `track01.ja.srt`
    lower_stem = stem.lower()
    for audio_ext in AUDIO_EXTENSIONS:
        if lower_stem.endswith(audio_ext):
            stem = stem[: -len(audio_ext)]
            break
    stem = _LANG_SUFFIX_RE.sub("", stem)
    if path.suffix.lower() in SCRIPT_EXTENSIONS:
        stripped_script = _SCRIPT_SUFFIX_RE.sub("", stem).strip(" _-.")
        if stripped_script:
            stem = stripped_script

    role = "main"
    try:
        rel_parts = path.parent.relative_to(root_dir).parts
    except ValueError:
        rel_parts = ()
    for part in reversed(rel_parts):
        mapped = _CONTAINER_DIR_MARKERS.get(part.strip().casefold())
        if mapped in {"vocals", "no_se", "se_only"}:
            role = mapped
            break

    for candidate_role, pattern in _STEM_ROLE_PATTERNS:
        match = pattern.search(stem)
        if match:
            stripped = stem[: match.start()].strip(" _-.")
            if stripped:
                stem = stripped
                if role == "main" or candidate_role != "main":
                    role = candidate_role
            break

    normalized_key = re.sub(r"[\s_\-]+", "_", stem.strip()).casefold()
    number_match = _TRACK_NUMBER_RE.match(stem.strip())
    track_num = int(number_match.group(1)) if number_match else None
    return normalized_key or path.stem.casefold(), role, track_num


def _probe_audio_metadata(audio_path: Path) -> dict[str, Any]:
    """Read audio duration, channels, and sample rate without loading full PCM into memory."""
    try:
        info = sf.info(str(audio_path))
        if info.samplerate > 0 and info.frames >= 0:
            return {
                "duration": round(float(info.duration), 4),
                "sample_rate": int(info.samplerate),
                "channels": int(info.channels),
                "format": audio_path.suffix.lower().lstrip("."),
            }
    except Exception:
        pass

    # Fallback via FFmpeg stderr header inspection / decode for containers like .m4a
    with tempfile.TemporaryDirectory(prefix="asmr-probe-") as temp_dir:
        probe_wav = Path(temp_dir) / "probe.wav"
        cmd = [
            get_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-vn",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(probe_wav),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not probe_wav.is_file():
            raise AppValidationError(f"Unable to read audio file {audio_path.name}: {result.stderr[-400:]}")
        info = sf.info(str(probe_wav))
        return {
            "duration": round(float(info.duration), 4),
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "format": audio_path.suffix.lower().lstrip("."),
        }


def _inspect_subtitle_file(sub_path: Path) -> dict[str, Any]:
    """Parse a subtitle file and summarize cue count, language, and bilingual structure."""
    fmt = sub_path.suffix.lower().lstrip(".")
    try:
        raw_text = sub_path.read_text(encoding="utf-8-sig")
        doc = SubtitleParser().parse_text(raw_text, fmt)
    except Exception as exc:
        return {
            "path": str(sub_path),
            "format": fmt,
            "valid": False,
            "cue_count": 0,
            "language": "unknown",
            "bilingual": False,
            "error": str(exc),
        }

    if not doc.segments:
        return {
            "path": str(sub_path),
            "format": fmt,
            "valid": False,
            "cue_count": 0,
            "language": "unknown",
            "bilingual": False,
            "error": "empty subtitle",
        }

    multi_line_count = 0
    first_lines: list[str] = []
    second_lines: list[str] = []
    all_texts: list[str] = []
    for seg in doc.segments:
        cleaned = re.sub(r"<[^>]*>", "", seg.text or "").replace("\r\n", "\n").strip()
        all_texts.append(cleaned)
        parts = (
            [p.strip() for p in cleaned.split(" / ") if p.strip()]
            if fmt == "lrc" and " / " in cleaned
            else [p.strip() for p in cleaned.split("\n") if p.strip()]
        )
        if len(parts) >= 2:
            multi_line_count += 1
            first_lines.append(parts[0])
            second_lines.append(" ".join(parts[1:]))
        elif parts:
            first_lines.append(parts[0])

    bilingual = False
    if multi_line_count >= max(1, len(doc.segments) // 3) and second_lines:
        lang1 = normalize_language_code(detect_subtitle_language(first_lines))
        lang2 = normalize_language_code(detect_subtitle_language(second_lines))
        bilingual = (lang1 != lang2 and "unknown" not in {lang1, lang2}) or multi_line_count == len(doc.segments)

    detected_lang = normalize_language_code(detect_subtitle_language(all_texts))
    return {
        "path": str(sub_path),
        "format": fmt,
        "valid": True,
        "cue_count": len(doc.segments),
        "language": "bilingual" if bilingual else detected_lang,
        "bilingual": bilingual,
    }


def _plan_slots_fallback(
    segments: Sequence[Mapping[str, Any]],
    take_durations: Sequence[float],
    *,
    reference_duration: float | None = None,
    guard_sec: float = 0.06,
    max_atempo: float = 1.35,
) -> list[dict[str, Any]]:
    """Compute post-cue silence slack and required atempo per cue."""
    results: list[dict[str, Any]] = []
    total = len(segments)
    for idx, (seg, duration) in enumerate(zip(segments, take_durations, strict=True)):
        start = float(seg["start"])
        end = float(seg["end"])
        natural_slot = max(0.01, end - start)
        if idx + 1 < total:
            next_start = float(segments[idx + 1]["start"])
            available_slack = max(0.0, next_start - guard_sec - end)
        elif reference_duration is not None and reference_duration > end:
            available_slack = max(0.0, float(reference_duration) - guard_sec - end)
        else:
            available_slack = 0.0

        max_effective_slot = natural_slot + available_slack
        borrowed_sec = min(available_slack, max(0.0, float(duration) - natural_slot))
        effective_slot = natural_slot + borrowed_sec if duration > natural_slot else natural_slot
        required_atempo = max(1.0, float(duration) / max(0.01, max_effective_slot))
        applied_atempo = min(required_atempo, max_atempo)
        results.append(
            {
                "natural_slot": natural_slot,
                "available_slack": available_slack,
                "borrowed_sec": borrowed_sec,
                "effective_slot": effective_slot if duration <= natural_slot else max_effective_slot,
                "max_effective_slot": max_effective_slot,
                "required_atempo": required_atempo,
                "applied_atempo": applied_atempo,
                "over_speed": required_atempo > max_atempo,
            }
        )
    return results


def _plan_cue_slots_compatible(
    segments: Sequence[Mapping[str, Any]],
    take_durations: Sequence[float],
    *,
    reference_duration: float | None = None,
    guard_sec: float = 0.06,
    max_atempo: float = 1.35,
) -> list[dict[str, Any]]:
    """Delegate to `src.mixer.binaural.plan_cue_slots` when present, else use identical fallback."""
    fallback = _plan_slots_fallback(
        segments,
        take_durations,
        reference_duration=reference_duration,
        guard_sec=guard_sec,
        max_atempo=max_atempo,
    )
    try:
        from src.mixer.binaural import plan_cue_slots  # type: ignore[import-not-found]
    except ImportError:
        return fallback

    timeline = [{"start_time": float(s["start"]), "end_time": float(s["end"])} for s in segments]
    planned = plan_cue_slots(
        timeline,
        list(take_durations),
        reference_duration=reference_duration,
        guard_sec=guard_sec,
        max_atempo=max_atempo,
    )
    merged: list[dict[str, Any]] = []
    for base, item in zip(fallback, planned, strict=True):
        merged.append({**base, **dict(item)})
    return merged


class DraftSessionService:
    """Domain service orchestrating Two-Phase DraftSession (`PREPARE -> AWAITING_REVIEW -> COMMIT`)."""

    def __init__(
        self,
        *,
        store: DraftStore | None = None,
        asr_service: Any | None = None,
        llm_service: Any | None = None,
        llm_runtime: Any | None = None,
        speech_service: Any | None = None,
        artifact_service: Any | None = None,
        mixer_factory: Callable[..., Mixer] | None = None,
    ) -> None:
        self._store = store
        self._asr_service = asr_service
        self._llm_service = llm_service
        self._llm_runtime = llm_runtime
        self._speech_service = speech_service
        self._artifact_service = artifact_service
        self._mixer_factory = mixer_factory or Mixer
        self._exporter = SubtitleExporter()
        self._parser = SubtitleParser()

    @property
    def store(self) -> DraftStore:
        return self._store if self._store is not None else get_draft_store()

    def _get_asr_service(self) -> Any:
        if self._asr_service is not None:
            return self._asr_service
        from src.app.services.asr_engine_service import get_asr_engine_service

        return get_asr_engine_service()

    def _get_llm_service(self) -> Any:
        if self._llm_service is not None:
            return self._llm_service
        from src.app.services.llm_capability_service import get_llm_capability_service

        return get_llm_capability_service()

    def _get_speech_service(self) -> Any:
        if self._speech_service is not None:
            return self._speech_service
        voice_lab_override = os.environ.get("ASMR_HELPER_VOICE_LAB_DIR", "").strip()
        data_dir_override = os.environ.get("ASMR_HELPER_DATA_DIR", "").strip()
        if voice_lab_override:
            from src.app.services.speech_service import SpeechService

            self._speech_service = SpeechService(store=SpeechStore(Path(voice_lab_override)))
            return self._speech_service
        if data_dir_override:
            from src.config import PROJECT_ROOT

            default_store_json = PROJECT_ROOT / "config" / "voice_lab" / "store.json"
            if not default_store_json.exists():
                from src.app.services.speech_service import SpeechService

                self._speech_service = SpeechService(
                    store=SpeechStore(Path(data_dir_override).expanduser().resolve() / "voice_lab")
                )
                return self._speech_service
        from src.app.services.speech_service import get_speech_service

        return get_speech_service()

    def _is_llm_available(self, explicit_provider: str | None = None) -> bool:
        if self._llm_service is not None or self._llm_runtime is not None or explicit_provider:
            return True
        try:
            from src.config import config
            from src.provider_profiles import profiles_for

            profiles = profiles_for(config.to_dict())
            active_id = profiles.get("active_llm")
            active = next((p for p in profiles.get("llm", []) if p.get("id") == active_id), None)
            return bool(active and str(active.get("api_key", "")).strip())
        except Exception:
            return False

    def _staging_dir(self, draft_id: str) -> Path:
        root = self.store.db_path.parent / "drafts" / draft_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    # ─── Phase 0: Work Inspection & Stem Auto-Pairing ─────────────────────

    def inspect_work(self, path_or_dir: str | Path) -> dict[str, Any]:
        """Inspect a work file or directory, discovering audio tracks, companions, and stem pairs."""
        raw = str(path_or_dir or "").strip()
        if not raw:
            raise AppValidationError("path_or_dir must be non-empty")
        target = Path(raw).expanduser().resolve()
        if not target.exists():
            raise AppValidationError(f"Work path does not exist: {target}")

        if target.is_file():
            work_dir = target.parent
            title = target.stem
            focus_file: Path | None = target
        elif target.is_dir():
            work_dir = target
            title = target.name
            focus_file = None
        else:
            raise AppValidationError(f"Unsupported path type: {target}")

        audio_paths: list[Path] = []
        subtitle_paths: list[Path] = []
        script_paths: list[Path] = []

        def _scan_dir(current: Path, depth: int = 0) -> None:
            if depth > 4:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                return
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    if entry.name.casefold() in _SKIP_DIR_NAMES:
                        continue
                    _scan_dir(entry, depth + 1)
                elif entry.is_file():
                    suffix = entry.suffix.lower()
                    if suffix in AUDIO_EXTENSIONS:
                        audio_paths.append(entry)
                    elif suffix in SUBTITLE_EXTENSIONS:
                        subtitle_paths.append(entry)
                    elif suffix in SCRIPT_EXTENSIONS:
                        script_paths.append(entry)

        _scan_dir(work_dir)
        if focus_file is not None and focus_file.suffix.lower() in AUDIO_EXTENSIONS and focus_file not in audio_paths:
            audio_paths.insert(0, focus_file)

        # Inspect audio files & group into logical tracks by stem / track number
        audio_inventory: list[dict[str, Any]] = []
        groups: dict[str, dict[str, Any]] = {}
        number_to_group_key: dict[int, str] = {}

        for audio_path in audio_paths:
            meta = _probe_audio_metadata(audio_path)
            stem_key, role, track_num = _normalize_stem_and_role(audio_path, work_dir)
            item = {
                "path": str(audio_path),
                "name": audio_path.name,
                "stem_key": stem_key,
                "role": role,
                "track_number": track_num,
                **meta,
            }
            audio_inventory.append(item)

            resolved_group_key = stem_key
            if resolved_group_key not in groups and track_num is not None and track_num in number_to_group_key:
                # Pair e.g. `01_morning.wav` with `01_no_se.wav` when stem_key reduced to `01`
                existing_key = number_to_group_key[track_num]
                if stem_key == str(track_num) or existing_key == str(track_num):
                    resolved_group_key = existing_key

            group = groups.setdefault(
                resolved_group_key,
                {
                    "stem_key": resolved_group_key,
                    "track_number": track_num,
                    "main": [],
                    "vocals": [],
                    "no_se": [],
                    "se_only": [],
                },
            )
            if track_num is not None and track_num not in number_to_group_key:
                number_to_group_key[track_num] = resolved_group_key
            group[role].append(item)

        # Inspect subtitles and scripts
        subtitle_inventory = [_inspect_subtitle_file(sub_path) for sub_path in subtitle_paths]
        script_inventory = [
            {
                "path": str(script_path),
                "format": script_path.suffix.lower().lstrip("."),
                "size_bytes": script_path.stat().st_size,
            }
            for script_path in script_paths
        ]

        tracks: list[dict[str, Any]] = []
        stem_pairs: list[dict[str, Any]] = []

        def _sort_audio_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(
                items,
                key=lambda x: (
                    0 if focus_file is not None and Path(x["path"]) == focus_file else 1,
                    _FORMAT_PRIORITY.get("." + x["format"], 99),
                    x["name"].casefold(),
                ),
            )

        sorted_groups = sorted(
            groups.values(),
            key=lambda g: (
                g["track_number"] if g["track_number"] is not None else 9999,
                g["stem_key"],
            ),
        )

        for idx, group in enumerate(sorted_groups, start=1):
            main_candidates = _sort_audio_candidates(group["main"])
            vocals_candidates = _sort_audio_candidates(group["vocals"])
            no_se_candidates = _sort_audio_candidates(group["no_se"])
            se_only_candidates = _sort_audio_candidates(group["se_only"])

            primary = (
                main_candidates[0]
                if main_candidates
                else (no_se_candidates[0] if no_se_candidates else (vocals_candidates[0] if vocals_candidates else se_only_candidates[0]))
            )
            if focus_file is not None and focus_file.suffix.lower() in AUDIO_EXTENSIONS:
                # When inspecting a single specific track file, keep only its matching stem group first
                all_group_paths = {
                    Path(x["path"])
                    for bucket in ("main", "vocals", "no_se", "se_only")
                    for x in group[bucket]
                }
                if focus_file not in all_group_paths:
                    continue

            alternates = [
                item["path"]
                for item in main_candidates[1:]
                if item["path"] != primary["path"]
            ]
            paired_stems = {
                "vocals": vocals_candidates[0]["path"] if vocals_candidates and vocals_candidates[0]["path"] != primary["path"] else None,
                "no_se": no_se_candidates[0]["path"] if no_se_candidates and no_se_candidates[0]["path"] != primary["path"] else None,
                "se_only": se_only_candidates[0]["path"] if se_only_candidates and se_only_candidates[0]["path"] != primary["path"] else None,
                "alternates": alternates,
            }

            # Pair matching subtitles to this track
            paired_subs: list[dict[str, Any]] = []
            for sub_info in subtitle_inventory:
                sub_p = Path(sub_info["path"])
                sub_key, _, sub_num = _normalize_stem_and_role(sub_p, work_dir)
                if (
                    sub_key == group["stem_key"]
                    or sub_p.stem.casefold().startswith(Path(primary["path"]).stem.casefold())
                    or (group["track_number"] is not None and sub_num == group["track_number"] and len(sorted_groups) > 1)
                    or (len(sorted_groups) == 1 and len(subtitle_inventory) == 1)
                ):
                    paired_subs.append(sub_info)

            # Pair matching scripts (.txt / .pdf) to this track
            paired_scripts: list[str] = []
            for script_info in script_inventory:
                scr_p = Path(script_info["path"])
                scr_key, _, scr_num = _normalize_stem_and_role(scr_p, work_dir)
                if (
                    scr_key == group["stem_key"]
                    or (group["track_number"] is not None and scr_num == group["track_number"])
                    or len(script_inventory) == 1
                ):
                    paired_scripts.append(script_info["path"])

            track_record = {
                "track_id": f"track-{idx:02d}",
                "stem": group["stem_key"],
                "path": primary["path"],
                "duration": primary["duration"],
                "sample_rate": primary["sample_rate"],
                "channels": primary["channels"],
                "format": primary["format"],
                "paired_stems": paired_stems,
                "paired_subtitles": paired_subs,
                "paired_scripts": paired_scripts,
            }
            tracks.append(track_record)

            if any([paired_stems["vocals"], paired_stems["no_se"], paired_stems["se_only"], paired_subs, paired_scripts]):
                stem_pairs.append(
                    {
                        "stem": group["stem_key"],
                        "primary_audio": primary["path"],
                        "vocals": paired_stems["vocals"],
                        "no_se": paired_stems["no_se"],
                        "se_only": paired_stems["se_only"],
                        "subtitles": [s["path"] for s in paired_subs],
                        "scripts": paired_scripts,
                    }
                )

        has_audio = len(tracks) > 0
        valid_subs = [s for t in tracks for s in t["paired_subtitles"] if s.get("valid")]
        if not valid_subs and not tracks:
            valid_subs = [s for s in subtitle_inventory if s.get("valid")]

        has_bilingual_or_target = any(
            s.get("bilingual") or s.get("language") in {"zh", "en"}
            for s in valid_subs
        )
        has_source_subs = any(
            s.get("language") in {"ja", "bilingual"}
            for s in valid_subs
        )
        has_clean_stem = any(
            bool(t["paired_stems"].get("vocals") or t["paired_stems"].get("no_se"))
            for t in tracks
        )
        has_scripts = bool(script_inventory)

        if not has_audio:
            recommended_mode = "empty"
        elif has_bilingual_or_target:
            recommended_mode = "subtitle_ready"
        elif has_source_subs:
            recommended_mode = "translate_existing_subtitle"
        else:
            recommended_mode = "asr_and_translate"

        warnings: list[str] = []
        if not has_audio:
            warnings.append("未在指定路径发现受支持的音频文件 (.wav/.flac/.mp3/.m4a/.ogg)。")
        for sub in subtitle_inventory:
            if not sub.get("valid"):
                warnings.append(f"字幕文件无法解析: {Path(sub['path']).name} ({sub.get('error', 'invalid')})")

        return {
            "work_dir": str(work_dir),
            "title": title,
            "tracks": tracks,
            "audio_files": audio_inventory,
            "subtitles": subtitle_inventory,
            "scripts": script_inventory,
            "stem_pairs": stem_pairs,
            "readiness": {
                "has_audio": has_audio,
                "track_count": len(tracks),
                "has_source_subtitles": has_source_subs,
                "has_target_or_bilingual_subtitles": has_bilingual_or_target,
                "has_scripts": has_scripts,
                "has_clean_vocal_or_no_se_stem": has_clean_stem,
                "recommended_mode": recommended_mode,
                "warnings": warnings,
            },
        }

    # ─── Deterministic QualityAuditReport ─────────────────────────────────

    def compute_quality_audit(
        self,
        segments: Sequence[Mapping[str, Any]],
        *,
        source_lang: str = "ja",
        target_lang: str = "zh",
        reference_duration: float | None = None,
        chars_per_second: float = 4.2,
        max_atempo: float = 1.35,
        guard_sec: float = 0.06,
        reference_quality: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compute deterministic Phase-1/patch QualityAuditReport for `segments`."""
        if chars_per_second <= 0 or not math.isfinite(chars_per_second):
            raise AppValidationError("chars_per_second must be a positive finite number")
        if max_atempo < 1.0 or not math.isfinite(max_atempo):
            raise AppValidationError("max_atempo must be >= 1.0")

        norm_source = normalize_language_code(source_lang)
        norm_target = normalize_language_code(target_lang)

        untranslated_indices: list[int] = []
        japanese_residue_indices: list[int] = []
        empty_or_symbol_indices: list[int] = []
        estimated_durations: list[float] = []
        char_counts: list[int] = []
        translated_count = 0

        for idx, seg in enumerate(segments):
            source_text = str(seg.get("source_text", "") or "").strip()
            translation = str(seg.get("translation", "") or "").strip()
            source_has_speech = has_speech_text(source_text)
            trans_has_speech = has_speech_text(translation)

            if not source_has_speech and not trans_has_speech:
                empty_or_symbol_indices.append(idx)
                estimated_durations.append(0.0)
                char_counts.append(0)
                continue

            if not translation:
                if source_has_speech:
                    untranslated_indices.append(idx)
                else:
                    empty_or_symbol_indices.append(idx)
                estimated_durations.append(0.0)
                char_counts.append(0)
                continue

            if not trans_has_speech:
                # Non-empty symbol-only translation (e.g., "..." or "♪")
                empty_or_symbol_indices.append(idx)
                estimated_durations.append(0.0)
                char_counts.append(0)
                continue

            # Check identical untranslated copy when languages differ
            if (
                norm_source != norm_target
                and source_text
                and translation == source_text
                and (norm_target != "ja" and has_japanese_residue(translation))
            ):
                untranslated_indices.append(idx)

            translated_count += 1
            if norm_target != "ja" and has_japanese_residue(translation):
                japanese_residue_indices.append(idx)

            units = count_spoken_units(translation)
            char_counts.append(units)
            estimated_durations.append(units / chars_per_second if units > 0 else 0.0)

        slot_plans = (
            _plan_cue_slots_compatible(
                segments,
                estimated_durations,
                reference_duration=reference_duration,
                guard_sec=guard_sec,
                max_atempo=max_atempo,
            )
            if segments
            else []
        )

        over_speed_cues: list[dict[str, Any]] = []
        for idx, (seg, units, est_dur, slot) in enumerate(
            zip(segments, char_counts, estimated_durations, slot_plans, strict=True)
        ):
            if units <= 0 or est_dur <= 0:
                continue
            start = float(seg["start"])
            end = float(seg["end"])
            cue_duration = max(0.01, end - start)
            available_slack = float(slot.get("available_slack", 0.0))
            max_slot = float(slot.get("max_effective_slot", cue_duration + available_slack))
            predicted_atempo = est_dur / max(0.01, max_slot)
            if predicted_atempo > max_atempo or bool(slot.get("over_speed", False)):
                max_chars = max(1, int(math.floor(max_slot * chars_per_second * max_atempo)))
                over_speed_cues.append(
                    {
                        "index": idx,
                        "cue_id": str(seg.get("cue_id") or f"cue-{idx + 1:04d}"),
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "cue_duration": round(cue_duration, 3),
                        "available_slack": round(available_slack, 3),
                        "effective_slot": round(max_slot, 3),
                        "char_count": units,
                        "estimated_duration": round(est_dur, 3),
                        "predicted_atempo": round(predicted_atempo, 3),
                        "max_recommended_chars": max_chars,
                        "source_text": str(seg.get("source_text", "")),
                        "translation": str(seg.get("translation", "")),
                    }
                )

        # Symbol-only translations on cues whose source actually had speech also block gate
        blocking_empty = [
            idx
            for idx in empty_or_symbol_indices
            if has_speech_text(str(segments[idx].get("source_text", "")))
        ]
        gate_passed = (
            len(segments) > 0
            and translated_count > 0
            and len(untranslated_indices) == 0
            and len(japanese_residue_indices) == 0
            and len(over_speed_cues) == 0
            and len(blocking_empty) == 0
        )

        return {
            "untranslated_indices": untranslated_indices,
            "japanese_residue_indices": japanese_residue_indices,
            "empty_or_symbol_indices": empty_or_symbol_indices,
            "over_speed_cues": over_speed_cues,
            "summary_counts": {
                "total_cues": len(segments),
                "translated_cues": translated_count,
                "untranslated_count": len(untranslated_indices),
                "japanese_residue_count": len(japanese_residue_indices),
                "empty_or_symbol_count": len(empty_or_symbol_indices),
                "over_speed_count": len(over_speed_cues),
            },
            "gate_passed": gate_passed,
            "chars_per_second": round(chars_per_second, 3),
            "max_atempo": round(max_atempo, 3),
            "reference_quality": deepcopy(reference_quality),
            "warnings": list(warnings or []),
        }

    # ─── Phase 1: Prepare Draft (`preparing` -> `awaiting_review`) ────────

    def _load_segments_from_subtitles(
        self,
        subtitle_paths: Sequence[str | Path],
        *,
        source_lang: str,
        target_lang: str,
    ) -> list[dict[str, Any]]:
        """Load source, target, or bilingual subtitle cues into canonical draft segments."""
        parsed_docs: list[tuple[Path, dict[str, Any], SubtitleDocument]] = []
        for raw_path in subtitle_paths:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file():
                raise AppValidationError(f"Subtitle file does not exist: {path}")
            summary = _inspect_subtitle_file(path)
            doc = self._parser.parse_text(
                path.read_text(encoding="utf-8-sig"),
                path.suffix.lower().lstrip("."),
            )
            if doc.segments:
                parsed_docs.append((path, summary, doc))

        if not parsed_docs:
            raise AppValidationError("Provided subtitle file contains no valid cues")

        norm_source = normalize_language_code(source_lang)
        norm_target = normalize_language_code(target_lang)

        # Priority 1: Explicit bilingual subtitle file
        bilingual_entry = next((item for item in parsed_docs if item[1].get("bilingual")), None)
        if bilingual_entry is not None:
            sub_path, _, doc = bilingual_entry
            fmt = sub_path.suffix.lower().lstrip(".")
            return self._segments_from_single_doc(doc, fmt=fmt, doc_lang="bilingual", source_lang=norm_source, target_lang=norm_target)

        # Priority 2: Separate source + target subtitle files with matching cues
        source_entry = next((item for item in parsed_docs if item[1].get("language") == norm_source), None)
        target_entry = next((item for item in parsed_docs if item[1].get("language") == norm_target), None)
        if source_entry is not None and target_entry is not None and source_entry[0] != target_entry[0]:
            src_doc = source_entry[2]
            tgt_doc = target_entry[2]
            tgt_by_ms = {
                (round(s.start * 1000), round(s.end * 1000)): re.sub(r"<[^>]*>", "", s.text).strip()
                for s in tgt_doc.segments
            }
            segments: list[dict[str, Any]] = []
            for idx, seg in enumerate(src_doc.segments):
                src_text = re.sub(r"<[^>]*>", "", seg.text).strip()
                key = (round(seg.start * 1000), round(seg.end * 1000))
                trans_text = tgt_by_ms.get(key, "")
                if not trans_text and idx < len(tgt_doc.segments) and len(src_doc.segments) == len(tgt_doc.segments):
                    trans_text = re.sub(r"<[^>]*>", "", tgt_doc.segments[idx].text).strip()
                segments.append(
                    {
                        "index": idx,
                        "cue_id": f"cue-{idx + 1:04d}",
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "source_text": src_text,
                        "translation": trans_text,
                        "speaker": None,
                        "delivery": "normal",
                        "emotion": "neutral",
                    }
                )
            return segments

        # Priority 3: Single subtitle file (source-only, target-only, or mixed)
        chosen_path, chosen_summary, chosen_doc = parsed_docs[0]
        return self._segments_from_single_doc(
            chosen_doc,
            fmt=chosen_path.suffix.lower().lstrip("."),
            doc_lang=str(chosen_summary.get("language", "unknown")),
            source_lang=norm_source,
            target_lang=norm_target,
        )

    def _segments_from_single_doc(
        self,
        doc: SubtitleDocument,
        *,
        fmt: str,
        doc_lang: str,
        source_lang: str,
        target_lang: str,
    ) -> list[dict[str, Any]]:
        raw_cues: list[tuple[float, float, list[str]]] = []
        multi_line_cues = 0
        for seg in doc.segments:
            cleaned = re.sub(r"<[^>]*>", "", seg.text or "").replace("\r\n", "\n").strip()
            parts = (
                [p.strip() for p in cleaned.split(" / ") if p.strip()]
                if fmt == "lrc" and " / " in cleaned
                else [p.strip() for p in cleaned.split("\n") if p.strip()]
            )
            if len(parts) >= 2:
                multi_line_cues += 1
            raw_cues.append((float(seg.start), float(seg.end), parts))

        segments: list[dict[str, Any]] = []
        treat_as_bilingual = doc_lang == "bilingual" or multi_line_cues > 0

        for idx, (start, end, parts) in enumerate(raw_cues):
            source_text = ""
            translation = ""
            if not parts:
                source_text = ""
                translation = ""
            elif len(parts) >= 2:
                source_text = parts[0]
                translation = "\n".join(parts[1:])
            else:
                line = parts[0]
                if not has_speech_text(line):
                    source_text = line
                    translation = ""
                elif treat_as_bilingual or doc_lang in {"mixed", "unknown"}:
                    line_lang = normalize_language_code(detect_subtitle_language([line]))
                    if (source_lang == "ja" and has_japanese_residue(line)) or line_lang == source_lang:
                        source_text = line
                        translation = ""
                    else:
                        source_text = ""
                        translation = line
                elif doc_lang == target_lang and source_lang != target_lang:
                    source_text = ""
                    translation = line
                else:
                    source_text = line
                    translation = ""

            segments.append(
                {
                    "index": idx,
                    "cue_id": f"cue-{idx + 1:04d}",
                    "start": start,
                    "end": end,
                    "source_text": source_text,
                    "translation": translation,
                    "speaker": None,
                    "delivery": "normal",
                    "emotion": "neutral",
                }
            )
        return segments

    def _extract_voice_reference_candidate(
        self,
        audio_path: Path,
        staging_dir: Path,
        segments: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Select highest RMS-to-noise-floor 6-10s clean window and write mono PCM_16 candidate."""
        info = _probe_audio_metadata(audio_path)
        total_duration = float(info["duration"])
        if total_duration <= 0.1:
            raise AppValidationError("Audio track is too short for voice reference extraction")

        # Decode via soundfile (or FFmpeg fallback for compressed containers) in blocks
        hop_sec = 0.1
        frame_rms: list[float] = []
        frame_clip: list[float] = []

        def _scan_stream(readable_path: Path) -> int:
            with sf.SoundFile(str(readable_path)) as stream:
                sr = stream.samplerate
                block_frames = max(1, int(round(hop_sec * sr)))
                for block in stream.blocks(blocksize=block_frames, dtype="float32", always_2d=True):
                    mono = np.mean(block, axis=1)
                    if len(mono) == 0:
                        continue
                    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
                    clip = float(np.mean(np.abs(mono) >= 0.995))
                    frame_rms.append(rms)
                    frame_clip.append(clip)
                return sr

        decoded_temp_dir: tempfile.TemporaryDirectory[str] | None = None
        readable = audio_path
        try:
            try:
                sample_rate = _scan_stream(readable)
            except Exception:
                decoded_temp_dir = tempfile.TemporaryDirectory(prefix="asmr-ref-decode-")
                readable = Path(decoded_temp_dir.name) / "decoded.wav"
                subprocess.run(
                    [
                        get_ffmpeg(),
                        "-nostdin",
                        "-v",
                        "error",
                        "-i",
                        str(audio_path),
                        "-vn",
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        "-y",
                        str(readable),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=180,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                frame_rms.clear()
                frame_clip.clear()
                sample_rate = _scan_stream(readable)

            rms_arr = np.asarray(frame_rms, dtype=np.float64)
            clip_arr = np.asarray(frame_clip, dtype=np.float64)
            if len(rms_arr) == 0:
                raise AppValidationError("Audio stream contains no readable samples")

            global_noise = float(np.percentile(rms_arr, 15)) + 1e-6
            min_win_sec = min(6.0, total_duration)
            max_win_sec = min(10.0, max(min_win_sec, total_duration))

            candidate_intervals: list[tuple[float, float]] = []
            # Slide 8s (clamped to [6, 10]s) windows at 0.5s steps
            target_win = min(8.0, max_win_sec)
            win_frames = max(1, int(round(target_win / hop_sec)))
            step_frames = max(1, int(round(0.5 / hop_sec)))
            for start_f in range(0, max(1, len(rms_arr) - win_frames + 1), step_frames):
                end_f = min(len(rms_arr), start_f + win_frames)
                candidate_intervals.append((start_f * hop_sec, min(total_duration, end_f * hop_sec)))

            # Also consider contiguous cue groups falling in [6.0, 10.0]s so transcript aligns cleanly
            for i in range(len(segments)):
                s_start = float(segments[i]["start"])
                for j in range(i, len(segments)):
                    s_end = float(segments[j]["end"])
                    span = s_end - s_start
                    if span > 10.0:
                        break
                    if span >= min_win_sec:
                        candidate_intervals.append((max(0.0, s_start), min(total_duration, s_end)))

            best_score = -1e9
            best_window = (0.0, min(total_duration, max_win_sec))
            best_snr_db = 0.0
            best_rms = 0.0

            for w_start, w_end in candidate_intervals:
                i0 = max(0, int(math.floor(w_start / hop_sec)))
                i1 = min(len(rms_arr), max(i0 + 1, int(math.ceil(w_end / hop_sec))))
                sub_rms = rms_arr[i0:i1]
                sub_clip = clip_arr[i0:i1]
                speech_level = float(np.percentile(sub_rms, 80))
                local_noise = max(global_noise, float(np.percentile(sub_rms, 15)) + 1e-6)
                snr_db = 20.0 * math.log10(max(speech_level, 1e-7) / local_noise)
                clip_penalty = 50.0 * float(np.mean(sub_clip))
                dur = w_end - w_start
                dur_bonus = 2.0 if 6.0 <= dur <= 10.0 else 0.0
                score = snr_db + dur_bonus - clip_penalty
                if score > best_score:
                    best_score = score
                    best_window = (w_start, w_end)
                    best_snr_db = snr_db
                    best_rms = float(np.sqrt(np.mean(np.square(sub_rms))))

            ref_start, ref_end = best_window
            out_path = staging_dir / "voice_reference_candidate.wav"
            with sf.SoundFile(str(readable)) as stream:
                first = max(0, min(stream.frames - 1, int(round(ref_start * sample_rate))))
                last = max(first + 1, min(stream.frames, int(round(ref_end * sample_rate))))
                stream.seek(first)
                samples = stream.read(last - first, dtype="float32", always_2d=True)
                mono_out = np.mean(samples, axis=1)
                sf.write(str(out_path), mono_out, sample_rate, subtype="PCM_16")
        finally:
            if decoded_temp_dir is not None:
                decoded_temp_dir.cleanup()

        overlapping_texts = [
            str(seg.get("source_text") or "").strip()
            for seg in segments
            if float(seg["end"]) > ref_start + 0.05 and float(seg["start"]) < ref_end - 0.05
            and str(seg.get("source_text") or "").strip()
        ]
        return {
            "path": str(out_path),
            "source_audio_path": str(audio_path),
            "start": round(ref_start, 3),
            "end": round(ref_end, 3),
            "duration": round(ref_end - ref_start, 3),
            "sample_rate": sample_rate,
            "snr_db": round(best_snr_db, 2),
            "rms": round(best_rms, 5),
            "transcript": " ".join(overlapping_texts),
        }

    @staticmethod
    def _cue_cache_key(snapshot: Mapping[str, Any], text: str, delivery: str, emotion: str) -> str:
        recipe = snapshot.get("recipe", {})
        raw_recipe_id = str(recipe.get("id", ""))
        stable_recipe_id = "" if raw_recipe_id.startswith("pipeline-") else raw_recipe_id
        payload = {
            "recipe_id": stable_recipe_id,
            "recipe_revision": recipe.get("revision", 1),
            "provider_id": recipe.get("provider_id", ""),
            "model": recipe.get("model", ""),
            "mode": recipe.get("mode", ""),
            "connection_ref": recipe.get("connection_ref", ""),
            "language": recipe.get("language", ""),
            "variant": recipe.get("variant", {}),
            "provider_options": recipe.get("provider_options", {}),
            "text": text,
            "delivery": delivery,
            "emotion": emotion,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _resolve_speech_snapshot(self, speech_service: Any, voice_plan: Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(voice_plan.get("snapshot"), dict):
            return deepcopy(voice_plan["snapshot"])
        recipe_id = voice_plan.get("recipe_id")
        if recipe_id:
            if "speech_overrides" in voice_plan and hasattr(speech_service, "pipeline_snapshot"):
                return speech_service.pipeline_snapshot(
                    {
                        "provider": voice_plan.get("provider_id"),
                        "model": voice_plan.get("model"),
                        "options": {
                            "speech_recipe_id": recipe_id,
                            "speech_overrides": voice_plan["speech_overrides"],
                        },
                    }
                )
            return speech_service.snapshot(recipe_id)

        provider_id = voice_plan.get("provider_id") or "edge"
        model = voice_plan.get("model") or ("edge-tts" if provider_id == "edge" else None)
        options: dict[str, Any] = {}
        if voice_plan.get("voice"):
            options["voice"] = voice_plan["voice"]
        elif provider_id == "edge" and not voice_plan.get("speech_source"):
            options["voice"] = "zh-CN-XiaoxiaoNeural"
        if voice_plan.get("language"):
            options["language"] = voice_plan["language"]
        else:
            options["language"] = "zh"
        if isinstance(voice_plan.get("speech_source"), dict):
            options["speech_source"] = deepcopy(voice_plan["speech_source"])
        if "speed" in voice_plan:
            options["speed"] = voice_plan["speed"]
        return speech_service.pipeline_snapshot(
            {
                "provider": provider_id,
                "model": model,
                "options": options,
            }
        )

    def _create_managed_task(self, speech_service: Any, *, task_type: str, draft_id: str) -> str:
        tasks_svc = getattr(speech_service, "tasks", None)
        if tasks_svc is not None and hasattr(tasks_svc, "create_task_spec"):
            spec, _ = tasks_svc.create_task_spec(
                task_type="speech.generate",
                task_source="draft-session",
                session_id=draft_id,
                execution_profile={"draft_id": draft_id, "draft_operation": task_type},
            )
            if hasattr(tasks_svc, "start_task"):
                tasks_svc.start_task(spec.task_id, message=f"Running {task_type}", stage="tts")
            return str(spec.task_id)
        return f"{task_type.replace('.', '-')}-{uuid4().hex[:12]}"

    def _finish_managed_task(
        self,
        speech_service: Any,
        task_id: str,
        *,
        error: Exception | None = None,
    ) -> None:
        tasks_svc = getattr(speech_service, "tasks", None)
        if tasks_svc is None:
            return
        try:
            if error is None and hasattr(tasks_svc, "complete_task"):
                tasks_svc.complete_task(task_id, message="Completed", stage="export")
            elif error is not None and hasattr(tasks_svc, "fail_task"):
                tasks_svc.fail_task(task_id, message=str(error), stage="tts")
        except Exception:
            pass

    def _synthesize_sample_cues(
        self,
        *,
        draft_id: str,
        segments: Sequence[Mapping[str, Any]],
        voice_plan: Mapping[str, Any],
        staging_dir: Path,
        sample_count: int,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], float | None]:
        """Synthesize 1-2 representative sample cues during Phase 1 without running full-track TTS."""
        candidates = [
            seg for seg in segments
            if has_speech_text(str(seg.get("translation", "")))
        ]
        if not candidates or sample_count <= 0:
            return [], {}, None

        bounded_count = min(2, max(1, int(sample_count)), len(candidates))
        chosen = [candidates[0]]
        if bounded_count > 1 and len(candidates) > 1:
            chosen.append(candidates[len(candidates) // 2])

        speech_service = self._get_speech_service()
        snapshot = self._resolve_speech_snapshot(speech_service, voice_plan)
        sample_takes: list[dict[str, Any]] = []
        take_cache: dict[str, dict[str, Any]] = {}
        total_units = 0
        total_dur = 0.0

        if isinstance(getattr(speech_service, "store", None), SpeechStore):
            task_id = self._create_managed_task(speech_service, task_type="draft.sample", draft_id=draft_id)
            try:
                text = "".join(str(seg["translation"]).strip() for seg in chosen)
                plan = build_plan(text)
                plan["segments"] = []
                cursor = 0
                for idx, seg in enumerate(chosen):
                    seg_text = str(seg["translation"]).strip()
                    end_pos = cursor + len(seg_text)
                    plan["segments"].append(
                        {
                            "id": f"sample-{idx + 1}",
                            "start": cursor,
                            "end": end_pos,
                            "delivery": seg.get("delivery") or snapshot["recipe"].get("default_delivery", "normal"),
                            "emotion": seg.get("emotion") or snapshot["recipe"].get("default_emotion", "neutral"),
                            "pause_ms": snapshot["recipe"].get("default_pause_ms", 0),
                        }
                    )
                    cursor = end_pos
                saved_plan = speech_service.store.create("plans", plan)
                experiment_id = uuid4().hex
                media_root = staging_dir / "samples" / experiment_id
                speech_service.store.create(
                    "experiments",
                    {
                        "id": experiment_id,
                        "name": f"草稿样音 {draft_id}",
                        "plan_id": saved_plan["id"],
                        "task_id": task_id,
                        "kind": "formal",
                        "media_root": str(media_root),
                        "snapshot": snapshot,
                    },
                )
                requests = compile_recipe(snapshot["recipe"], saved_plan, snapshot["assets"])
                takes = speech_service.run_requests(
                    requests,
                    snapshot,
                    task_id=task_id,
                    experiment_id=experiment_id,
                    plan_id=saved_plan["id"],
                    media_root=media_root,
                )
                for seg, take in zip(chosen, takes, strict=True):
                    seg_text = str(seg["translation"]).strip()
                    dur = float(take["audio"]["duration"])
                    units = count_spoken_units(seg_text)
                    total_units += units
                    total_dur += dur
                    delivery = str(seg.get("delivery") or snapshot["recipe"].get("default_delivery", "normal"))
                    emotion = str(seg.get("emotion") or snapshot["recipe"].get("default_emotion", "neutral"))
                    cache_key = self._cue_cache_key(snapshot, seg_text, delivery, emotion)
                    take_cache[cache_key] = {
                        "take_id": take["id"],
                        "audio_path": take["audio_path"],
                        "duration": dur,
                    }
                    sample_takes.append(
                        {
                            "index": seg["index"],
                            "cue_id": seg["cue_id"],
                            "text": seg_text,
                            "audio_path": take["audio_path"],
                            "duration": round(dur, 3),
                            "take_id": take["id"],
                        }
                    )
                self._finish_managed_task(speech_service, task_id)
            except Exception as exc:
                self._finish_managed_task(speech_service, task_id, error=exc)
                raise
        elif hasattr(speech_service, "synthesize_text"):
            for idx, seg in enumerate(chosen):
                seg_text = str(seg["translation"]).strip()
                out_wav = staging_dir / "samples" / f"sample_{idx + 1:02d}.wav"
                out_wav.parent.mkdir(parents=True, exist_ok=True)
                speech_service.synthesize_text(snapshot, seg_text, str(out_wav))
                dur = _probe_audio_metadata(out_wav)["duration"] if out_wav.is_file() else 0.0
                units = count_spoken_units(seg_text)
                total_units += units
                total_dur += dur
                sample_takes.append(
                    {
                        "index": seg["index"],
                        "cue_id": seg["cue_id"],
                        "text": seg_text,
                        "audio_path": str(out_wav),
                        "duration": round(dur, 3),
                    }
                )

        measured_rate = (total_units / total_dur) if total_units >= 4 and total_dur > 0.2 else None
        return sample_takes, take_cache, measured_rate

    def prepare_draft(
        self,
        path_or_dir: str | Path,
        *,
        track_path: str | Path | None = None,
        subtitle_path: str | Path | None = None,
        script_path: str | Path | None = None,
        title: str | None = None,
        source_lang: str = "ja",
        target_lang: str = "zh",
        enable_translation: bool = True,
        force_asr: bool = False,
        asr_provider: str | None = None,
        asr_model: str | None = None,
        asr_options: dict[str, Any] | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_options: dict[str, Any] | None = None,
        voice_plan: dict[str, Any] | None = None,
        extract_voice_reference: bool = False,
        synthesize_samples: bool = False,
        sample_cue_count: int = 0,
        chars_per_second: float = 4.2,
        max_atempo: float = 1.35,
    ) -> dict[str, Any]:
        """Execute Phase 1 (`preparing -> awaiting_review`) and return the persisted draft."""
        inspection = self.inspect_work(path_or_dir)
        tracks = inspection["tracks"]
        if not tracks and subtitle_path is None:
            raise AppValidationError(f"No supported audio tracks discovered in {inspection['work_dir']}")

        primary_track: dict[str, Any] | None = None
        if track_path is not None:
            resolved_track = str(Path(track_path).expanduser().resolve())
            primary_track = next((t for t in tracks if Path(t["path"]).resolve() == Path(resolved_track)), None)
            if primary_track is None:
                if not Path(resolved_track).is_file():
                    raise AppValidationError(f"Requested track_path does not exist: {track_path}")
                meta = _probe_audio_metadata(Path(resolved_track))
                primary_track = {
                    "track_id": "track-01",
                    "stem": Path(resolved_track).stem,
                    "path": resolved_track,
                    **meta,
                    "paired_stems": {"vocals": None, "no_se": None, "se_only": None, "alternates": []},
                    "paired_subtitles": [],
                    "paired_scripts": [],
                }
                tracks = [primary_track, *tracks]
        elif tracks:
            primary_track = tracks[0]

        resolved_title = (title or "").strip() or (
            Path(primary_track["path"]).stem if primary_track and len(tracks) == 1 else inspection["title"]
        )
        draft_id = f"draft-{uuid4().hex[:12]}"
        resolved_voice_plan: dict[str, Any] = {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "chars_per_second": chars_per_second,
            "max_atempo": max_atempo,
            **deepcopy(voice_plan or {}),
        }
        if script_path is not None:
            resolved_voice_plan["script_path"] = str(Path(script_path).expanduser().resolve())
        elif primary_track and primary_track.get("paired_scripts"):
            resolved_voice_plan.setdefault("script_path", primary_track["paired_scripts"][0])

        self.store.create_draft(
            draft_id=draft_id,
            state="preparing",
            work_dir=inspection["work_dir"],
            title=resolved_title,
            tracks=tracks,
            segments=[],
            voice_plan=resolved_voice_plan,
            audit_report={},
            artifacts={"primary_track_path": primary_track["path"] if primary_track else None},
            revision=1,
        )

        warnings: list[str] = []
        try:
            staging_dir = self._staging_dir(draft_id)
            candidate_subtitles: list[str] = []
            if subtitle_path is not None:
                candidate_subtitles = [str(Path(subtitle_path).expanduser().resolve())]
            elif not force_asr and primary_track is not None:
                candidate_subtitles = [
                    s["path"] for s in primary_track.get("paired_subtitles", []) if s.get("valid")
                ]

            loaded_from_existing_subtitles = False
            if candidate_subtitles and not force_asr:
                segments = self._load_segments_from_subtitles(
                    candidate_subtitles,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
                loaded_from_existing_subtitles = True
                subtitle_source_mode = "existing_subtitle"
            else:
                if primary_track is None:
                    raise AppValidationError("Audio track is required when running ASR")
                asr_audio_path = (
                    primary_track["paired_stems"].get("vocals")
                    or primary_track["paired_stems"].get("no_se")
                    or primary_track["path"]
                )
                asr_svc = self._get_asr_service()
                transcription = asr_svc.transcribe_file(
                    input_path=str(asr_audio_path),
                    provider=asr_provider,
                    model=asr_model,
                    language=source_lang,
                    provider_options=asr_options,
                )
                segments = [
                    {
                        "index": idx,
                        "cue_id": f"cue-{idx + 1:04d}",
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "source_text": str(seg.text).strip(),
                        "translation": "",
                        "speaker": None,
                        "delivery": "normal",
                        "emotion": "neutral",
                    }
                    for idx, seg in enumerate(transcription.segments)
                    if float(seg.end) > float(seg.start)
                ]
                subtitle_source_mode = "asr"

            # Run optional LLM translation when cues have no translations yet (source-only subtitle or ASR)
            has_any_existing_translation = any(
                bool(str(s.get("translation", "")).strip()) for s in segments
            )
            should_translate = (
                enable_translation
                and normalize_language_code(source_lang) != normalize_language_code(target_lang)
                and (not loaded_from_existing_subtitles or not has_any_existing_translation or llm_provider is not None)
            )
            if should_translate:
                indices_to_translate = [
                    idx
                    for idx, seg in enumerate(segments)
                    if not str(seg.get("translation", "")).strip()
                    and has_speech_text(str(seg.get("source_text", "")))
                ]
                if indices_to_translate:
                    if self._is_llm_available(llm_provider):
                        source_texts = [str(segments[i]["source_text"]) for i in indices_to_translate]
                        if self._llm_runtime is not None and self._llm_service is None:
                            translated_items = self._llm_runtime.translate_texts(
                                texts=source_texts,
                                profile={
                                    "provider": llm_provider or "deepseek",
                                    "model": llm_model,
                                    "common_options": {},
                                    "provider_options": llm_options or {},
                                },
                                source_lang=source_lang,
                                target_lang=target_lang,
                            )
                        else:
                            llm_res = self._get_llm_service().translate_texts(
                                texts=source_texts,
                                provider=llm_provider,
                                model=llm_model,
                                source_lang=source_lang,
                                target_lang=target_lang,
                                provider_options=llm_options,
                            )
                            translated_items = list(llm_res.items)
                        for seg_idx, trans_text in zip(indices_to_translate, translated_items, strict=False):
                            segments[seg_idx]["translation"] = str(trans_text or "").strip()
                    else:
                        warnings.append("未检测到已配置的 LLM 翻译凭据，保留未翻译原文并在质检报告中标记。")

            reference_quality: dict[str, Any] | None = None
            want_ref = bool(extract_voice_reference or resolved_voice_plan.get("mode") == "clone")
            if want_ref and primary_track is not None:
                clean_audio = Path(
                    primary_track["paired_stems"].get("vocals")
                    or primary_track["paired_stems"].get("no_se")
                    or primary_track["path"]
                )
                reference_quality = self._extract_voice_reference_candidate(clean_audio, staging_dir, segments)
                resolved_voice_plan["reference_candidate"] = reference_quality

            effective_sample_count = int(sample_cue_count) if sample_cue_count > 0 else (2 if synthesize_samples else 0)
            sample_takes: list[dict[str, Any]] = []
            take_cache: dict[str, dict[str, Any]] = {}
            effective_cps = chars_per_second
            if effective_sample_count > 0:
                sample_takes, take_cache, measured_cps = self._synthesize_sample_cues(
                    draft_id=draft_id,
                    segments=segments,
                    voice_plan=resolved_voice_plan,
                    staging_dir=staging_dir,
                    sample_count=effective_sample_count,
                )
                resolved_voice_plan["sample_takes"] = sample_takes
                if measured_cps is not None and "chars_per_second" not in (voice_plan or {}):
                    effective_cps = measured_cps
                    resolved_voice_plan["measured_chars_per_second"] = round(measured_cps, 3)

            ref_duration = float(primary_track["duration"]) if primary_track is not None else None
            audit_report = self.compute_quality_audit(
                segments,
                source_lang=source_lang,
                target_lang=target_lang,
                reference_duration=ref_duration,
                chars_per_second=effective_cps,
                max_atempo=max_atempo,
                reference_quality=reference_quality,
                warnings=warnings,
            )

            artifacts = {
                "primary_track_path": primary_track["path"] if primary_track else None,
                "subtitle_source_mode": subtitle_source_mode,
                "source_subtitles": candidate_subtitles,
                "reference_candidate": reference_quality,
                "sample_takes": sample_takes,
                "take_cache": take_cache,
                "subtitles": {},
                "dubbing": None,
            }

            updated = self.store.update_draft(
                draft_id,
                increment_revision=False,
                state="awaiting_review",
                tracks=tracks,
                segments=segments,
                voice_plan=resolved_voice_plan,
                audit_report=audit_report,
                artifacts=artifacts,
            )
            return updated.to_dict()
        except (AppValidationError, DraftConflictError):
            self.store.update_draft(draft_id, increment_revision=False, state="failed")
            raise
        except Exception as exc:
            self.store.update_draft(
                draft_id,
                increment_revision=False,
                state="failed",
                artifacts={"last_error": str(exc)},
            )
            raise AppExecutionError(f"Failed to prepare draft {draft_id}: {exc}") from exc

    # ─── Inspection & Patch (`awaiting_review` -> `awaiting_review`) ──────

    def list_drafts(
        self,
        *,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.store.list_drafts(state=state, limit=limit)]

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        return self.store.get_draft(draft_id).to_dict()

    def get_audit_report(self, draft_id: str) -> dict[str, Any]:
        record = self.store.get_draft(draft_id)
        return {
            "draft_id": record.draft_id,
            "state": record.state,
            "revision": record.revision,
            **deepcopy(record.audit_report),
        }

    def patch_draft(
        self,
        draft_id: str,
        edits: Sequence[Mapping[str, Any]] | None = None,
        voice_plan_patch: Mapping[str, Any] | None = None,
        expected_revision: int | None = None,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Apply cue text/timing edits or voice recipe updates and immediately recompute QualityAuditReport."""
        current = self.store.get_draft(draft_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise DraftConflictError(
                f"Draft {draft_id!r} revision conflict: expected {expected_revision}, current {current.revision}"
            )
        if current.state in {"preparing", "committing"}:
            raise AppValidationError(f"Cannot patch draft {draft_id!r} while state is {current.state!r}")

        segments = deepcopy(current.segments)
        cue_id_map = {str(seg.get("cue_id", "")): idx for idx, seg in enumerate(segments)}

        for edit in edits or []:
            if not isinstance(edit, Mapping):
                raise AppValidationError("Each segment edit must be an object")
            target_idx: int | None = None
            if "index" in edit and edit["index"] is not None:
                raw_idx = edit["index"]
                if isinstance(raw_idx, bool) or not isinstance(raw_idx, int):
                    raise AppValidationError("Segment edit 'index' must be an integer")
                target_idx = raw_idx
            elif "cue_id" in edit and edit["cue_id"]:
                target_idx = cue_id_map.get(str(edit["cue_id"]))
                if target_idx is None:
                    raise AppValidationError(f"Unknown cue_id in edit: {edit['cue_id']!r}")
            else:
                raise AppValidationError("Segment edit requires 'index' or 'cue_id'")

            if target_idx < 0 or target_idx >= len(segments):
                raise AppValidationError(f"Segment edit index out of range: {target_idx}")

            seg = segments[target_idx]
            if "translation" in edit and edit["translation"] is not None:
                seg["translation"] = str(edit["translation"])
            if "source_text" in edit and edit["source_text"] is not None:
                seg["source_text"] = str(edit["source_text"])
            if "speaker" in edit:
                seg["speaker"] = str(edit["speaker"]) if edit["speaker"] is not None else None
            if "delivery" in edit and edit["delivery"] is not None:
                seg["delivery"] = str(edit["delivery"])
            if "emotion" in edit and edit["emotion"] is not None:
                seg["emotion"] = str(edit["emotion"])

            new_start = float(edit["start"]) if "start" in edit and edit["start"] is not None else float(seg["start"])
            new_end = float(edit["end"]) if "end" in edit and edit["end"] is not None else float(seg["end"])
            if not (math.isfinite(new_start) and math.isfinite(new_end)) or new_start < 0 or new_end <= new_start:
                raise AppValidationError(
                    f"Invalid timing range [{new_start}, {new_end}] for cue index {target_idx}"
                )
            seg["start"] = new_start
            seg["end"] = new_end

        voice_plan = deepcopy(current.voice_plan)
        if voice_plan_patch:
            if not isinstance(voice_plan_patch, Mapping):
                raise AppValidationError("voice_plan_patch must be an object")
            voice_plan.update(deepcopy(dict(voice_plan_patch)))

        primary_duration: float | None = None
        if current.tracks:
            primary_duration = float(current.tracks[0].get("duration") or 0.0) or None

        chars_per_sec = float(
            voice_plan.get("measured_chars_per_second")
            or voice_plan.get("chars_per_second")
            or 4.2
        )
        max_atempo = float(voice_plan.get("max_atempo") or 1.35)
        audit_report = self.compute_quality_audit(
            segments,
            source_lang=str(voice_plan.get("source_lang") or "ja"),
            target_lang=str(voice_plan.get("target_lang") or "zh"),
            reference_duration=primary_duration,
            chars_per_second=chars_per_sec,
            max_atempo=max_atempo,
            reference_quality=voice_plan.get("reference_candidate"),
            warnings=current.audit_report.get("warnings", []),
        )

        updated = self.store.update_draft(
            draft_id,
            expected_revision=expected_revision if expected_revision is not None else current.revision,
            increment_revision=True,
            state="awaiting_review",
            title=title.strip() if isinstance(title, str) and title.strip() else None,
            segments=segments,
            voice_plan=voice_plan,
            audit_report=audit_report,
        )
        return updated.to_dict()

    # ─── Phase 2: Commit Draft (`committing` -> `completed`) ──────────────

    def _export_draft_subtitles(
        self,
        *,
        segments: Sequence[Mapping[str, Any]],
        output_dir: Path,
        base_stem: str,
        export_formats: Sequence[str],
        bilingual: bool,
    ) -> dict[str, str]:
        exported: dict[str, str] = {}
        safe_stem = sanitize_filename(base_stem).strip("_ ") or "output"
        for fmt_raw in export_formats:
            fmt = fmt_raw.lower().strip().lstrip(".")
            if fmt not in {"srt", "vtt", "lrc"}:
                raise AppValidationError(f"Unsupported subtitle export format: {fmt_raw!r}")
            out_path = output_dir / f"{safe_stem}.{fmt}"
            if bilingual:
                entries = []
                for seg in segments:
                    src = str(seg.get("source_text", "") or "").strip()
                    trn = str(seg.get("translation", "") or "").strip()
                    if not src and not trn:
                        continue
                    if src and trn:
                        entries.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": src, "translation": trn})
                    else:
                        entries.append({"start": float(seg["start"]), "end": float(seg["end"]), "text": trn or src, "translation": ""})
                self._exporter.export_bilingual_subtitle(entries, str(out_path), bilingual=True)
            else:
                doc = SubtitleDocument(
                    segments=[
                        DomainSubtitleSegment(
                            start=float(seg["start"]),
                            end=float(seg["end"]),
                            text=str(seg.get("translation") or seg.get("source_text") or "").strip(),
                        )
                        for seg in segments
                        if str(seg.get("translation") or seg.get("source_text") or "").strip()
                    ],
                    format=fmt,
                )
                self._exporter.export_document(doc, output_path=str(out_path), fmt=fmt)
            exported[fmt] = str(out_path)
        return exported

    def _synthesize_with_take_reuse(
        self,
        *,
        draft_id: str,
        spoken_cues: list[dict[str, Any]],
        voice_plan: Mapping[str, Any],
        tts_output_path: Path,
        reference_duration: float,
        binaural_source_path: str | None,
        prior_take_cache: Mapping[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], int, int]:
        """Synthesize timeline via SpeechService, reusing unchanged takes across commits."""
        speech_service = self._get_speech_service()
        snapshot = self._resolve_speech_snapshot(speech_service, voice_plan)
        updated_cache = deepcopy(dict(prior_take_cache))
        max_atempo = float(voice_plan.get("max_atempo") or 1.35)

        cue_keys = [
            self._cue_cache_key(snapshot, cue["text"], cue["delivery"], cue["emotion"])
            for cue in spoken_cues
        ]
        reusable_hits = [
            key in updated_cache and Path(str(updated_cache[key].get("audio_path", ""))).is_file()
            for key in cue_keys
        ]

        task_id = self._create_managed_task(speech_service, task_type="draft.commit", draft_id=draft_id)
        try:
            # Inspect optional binaural / slack kwargs supported by SpeechService
            timeline_sig = inspect.signature(speech_service.synthesize_timeline)
            extra_timeline_kwargs: dict[str, Any] = {}
            if "binaural_source_path" in timeline_sig.parameters and binaural_source_path:
                extra_timeline_kwargs["binaural_source_path"] = binaural_source_path
            if "borrow_silence_slack" in timeline_sig.parameters:
                extra_timeline_kwargs["borrow_silence_slack"] = True
            if "max_atempo" in timeline_sig.parameters:
                extra_timeline_kwargs["max_atempo"] = max_atempo

            has_real_store = isinstance(getattr(speech_service, "store", None), SpeechStore)

            # Fast path 1: Fresh commit (0 cached hits) -> call `synthesize_timeline` directly
            if not any(reusable_hits) or not has_real_store:
                assembly = speech_service.synthesize_timeline(
                    snapshot,
                    [
                        {
                            "text": cue["text"],
                            "start_time": cue["start_time"],
                            "end_time": cue["end_time"],
                        }
                        for cue in spoken_cues
                    ],
                    str(tts_output_path),
                    task_id,
                    reference_duration=reference_duration,
                    **extra_timeline_kwargs,
                )
                if has_real_store and isinstance(assembly, Mapping) and assembly.get("experiment_id"):
                    exp = speech_service.experiment(assembly["experiment_id"])
                    by_seg = {t["segment_id"]: t for t in exp.get("takes", [])}
                    for idx, key in enumerate(cue_keys):
                        take = by_seg.get(f"sentence-{idx + 1}")
                        if take and Path(take["audio_path"]).is_file():
                            updated_cache[key] = {
                                "take_id": take["id"],
                                "audio_path": take["audio_path"],
                                "duration": take.get("audio", {}).get("duration"),
                                "audio": deepcopy(take.get("audio", {})),
                                "compiled_request": deepcopy(take.get("compiled_request", {})),
                            }
                self._finish_managed_task(speech_service, task_id)
                return dict(assembly), updated_cache, 0, len(spoken_cues)

            # Incremental path: Reuse unchanged takes and run TTS ONLY for changed/new cues
            text = "".join(cue["text"] for cue in spoken_cues)
            plan = build_plan(text)
            plan["segments"] = []
            timeline: dict[str, dict[str, float]] = {}
            cursor = 0
            for idx, cue in enumerate(spoken_cues):
                end_pos = cursor + len(cue["text"])
                sid = f"sentence-{idx + 1}"
                plan["segments"].append(
                    {
                        "id": sid,
                        "start": cursor,
                        "end": end_pos,
                        "delivery": cue["delivery"],
                        "emotion": cue["emotion"],
                        "pause_ms": snapshot["recipe"].get("default_pause_ms", 0),
                    }
                )
                timeline[sid] = {"start": cue["start_time"], "end": cue["end_time"]}
                cursor = end_pos

            saved_plan = speech_service.store.create("plans", plan)
            experiment_id = uuid4().hex
            media_root = tts_output_path.resolve().parent / "speech" / experiment_id
            experiment = speech_service.store.create(
                "experiments",
                {
                    "id": experiment_id,
                    "name": f"正式配音 {task_id}",
                    "plan_id": saved_plan["id"],
                    "task_id": task_id,
                    "kind": "formal",
                    "media_root": str(media_root),
                    "snapshot": snapshot,
                    "timeline": timeline,
                    "reference_duration": reference_duration,
                },
            )
            requests = compile_recipe(snapshot["recipe"], saved_plan, snapshot["assets"])

            missing_requests: list[dict[str, Any]] = []
            missing_indices: list[int] = []
            reused_count = 0

            for idx, (req, key, is_hit) in enumerate(zip(requests, cue_keys, reusable_hits, strict=True)):
                if is_hit:
                    cached_entry = updated_cache[key]
                    src_audio = Path(str(cached_entry["audio_path"]))
                    info = sf.info(str(src_audio))
                    reused_take_id = uuid4().hex
                    reused_audio_dest = media_root / "audio" / f"{reused_take_id}.wav"
                    reused_audio_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src_audio, reused_audio_dest)
                    reused_take = speech_service.store.create(
                        "takes",
                        {
                            "id": reused_take_id,
                            "task_id": task_id,
                            "experiment_id": experiment["id"],
                            "plan_id": saved_plan["id"],
                            "recipe_id": snapshot["recipe"]["id"],
                            "segment_id": req["segment_id"],
                            "compiled_request": req,
                            "recipe_snapshot": deepcopy(snapshot["recipe"]),
                            "status": "completed",
                            "audio_path": str(reused_audio_dest),
                            "audio": {
                                "duration": info.duration,
                                "sample_rate": info.samplerate,
                                "channels": info.channels,
                                "format": info.format,
                            },
                            "elapsed_seconds": 0.0,
                            "reused": True,
                        },
                    )
                    speech_service.select(
                        {
                            "experiment_id": experiment["id"],
                            "segment_id": req["segment_id"],
                            "take_id": reused_take["id"],
                        }
                    )
                    reused_count += 1
                else:
                    missing_requests.append(req)
                    missing_indices.append(idx)

            if missing_requests:
                new_takes = speech_service.run_requests(
                    missing_requests,
                    snapshot,
                    task_id=task_id,
                    experiment_id=experiment["id"],
                    plan_id=saved_plan["id"],
                    media_root=media_root,
                )
                for idx, take in zip(missing_indices, new_takes, strict=True):
                    speech_service.select(
                        {
                            "experiment_id": experiment["id"],
                            "segment_id": take["segment_id"],
                            "take_id": take["id"],
                        }
                    )
                    updated_cache[cue_keys[idx]] = {
                        "take_id": take["id"],
                        "audio_path": take["audio_path"],
                        "duration": take.get("audio", {}).get("duration"),
                    }

            assemble_sig = inspect.signature(speech_service.assemble)
            extra_assemble_kwargs: dict[str, Any] = {}
            if "binaural_source_path" in assemble_sig.parameters and binaural_source_path:
                extra_assemble_kwargs["binaural_source_path"] = binaural_source_path
            if "borrow_silence_slack" in assemble_sig.parameters:
                extra_assemble_kwargs["borrow_silence_slack"] = True
            if "max_atempo" in assemble_sig.parameters:
                extra_assemble_kwargs["max_atempo"] = max_atempo

            assembly = speech_service.assemble(
                experiment["id"],
                output_path=str(tts_output_path),
                timeline=timeline,
                reference_duration=reference_duration,
                **extra_assemble_kwargs,
            )
            self._finish_managed_task(speech_service, task_id)
            return dict(assembly), updated_cache, reused_count, len(missing_requests)
        except Exception as exc:
            self._finish_managed_task(speech_service, task_id, error=exc)
            raise

    def commit_draft(
        self,
        draft_id: str,
        output_dir: str | Path,
        *,
        export_formats: Sequence[str] = ("srt", "lrc"),
        enable_dubbing: bool = True,
        bilingual: bool = True,
        mix_options: Mapping[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Execute Phase 2 (`committing -> completed`), exporting subtitles and optional dubbed mix."""
        raw_out = str(output_dir or "").strip()
        if not raw_out:
            raise AppValidationError("output_dir must be non-empty")

        current = self.store.get_draft(draft_id)
        if expected_revision is not None and current.revision != expected_revision:
            raise DraftConflictError(
                f"Draft {draft_id!r} revision conflict: expected {expected_revision}, current {current.revision}"
            )
        if current.state in {"preparing", "committing"}:
            raise AppValidationError(f"Cannot commit draft {draft_id!r} while state is {current.state!r}")
        if not current.segments:
            raise AppValidationError(f"Draft {draft_id!r} has no segments to commit")

        committing_record = self.store.update_draft(
            draft_id,
            expected_revision=expected_revision if expected_revision is not None else current.revision,
            increment_revision=True,
            state="committing",
        )

        try:
            target_dir = Path(raw_out).expanduser().resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            primary_track = committing_record.tracks[0] if committing_record.tracks else None
            base_stem = (
                Path(primary_track["path"]).stem
                if primary_track is not None
                else (committing_record.title or draft_id)
            )

            exported_subs = self._export_draft_subtitles(
                segments=committing_record.segments,
                output_dir=target_dir,
                base_stem=base_stem,
                export_formats=export_formats,
                bilingual=bilingual,
            )

            artifacts = deepcopy(committing_record.artifacts)
            artifacts["output_dir"] = str(target_dir)
            artifacts["subtitles"] = exported_subs

            if enable_dubbing:
                if primary_track is None:
                    raise AppValidationError("Dubbing requires an audio track in the draft session")
                default_delivery = str(committing_record.voice_plan.get("default_delivery") or "normal")
                default_emotion = str(committing_record.voice_plan.get("default_emotion") or "neutral")
                spoken_cues = [
                    {
                        "cue_id": str(seg.get("cue_id") or f"cue-{idx + 1:04d}"),
                        "text": str(seg.get("translation") or seg.get("source_text") or "").strip(),
                        "start_time": float(seg["start"]),
                        "end_time": float(seg["end"]),
                        "delivery": str(seg.get("delivery") or default_delivery),
                        "emotion": str(seg.get("emotion") or default_emotion),
                    }
                    for idx, seg in enumerate(committing_record.segments)
                    if has_speech_text(str(seg.get("translation") or seg.get("source_text") or ""))
                ]
                if not spoken_cues:
                    raise AppValidationError("Draft contains no speakable translated segments for dubbing")

                staging_dir = self._staging_dir(draft_id)
                tts_track_path = staging_dir / f"tts_timeline_rev{committing_record.revision}.wav"
                binaural_ref = (
                    primary_track.get("paired_stems", {}).get("vocals")
                    or primary_track.get("paired_stems", {}).get("no_se")
                    or primary_track["path"]
                )
                assembly, updated_cache, reused_count, synthesized_count = self._synthesize_with_take_reuse(
                    draft_id=draft_id,
                    spoken_cues=spoken_cues,
                    voice_plan=committing_record.voice_plan,
                    tts_output_path=tts_track_path,
                    reference_duration=float(primary_track.get("duration") or 0.0),
                    binaural_source_path=str(binaural_ref) if binaural_ref else None,
                    prior_take_cache=artifacts.get("take_cache") or {},
                )

                opts = dict(mix_options or {})
                se_only_stem = primary_track.get("paired_stems", {}).get("se_only")
                bg_audio_path = str(
                    opts.get("background_path")
                    or (se_only_stem if se_only_stem and opts.get("prefer_se_stem", True) else primary_track["path"])
                )
                mixer = self._mixer_factory(
                    original_volume=float(opts.get("original_volume", 0.95 if se_only_stem else 0.85)),
                    tts_volume_ratio=float(opts.get("tts_volume_ratio", 0.65)),
                    tts_delay_ms=float(opts.get("tts_delay_ms", 0.0)),
                )
                safe_stem = sanitize_filename(base_stem).strip("_ ") or "output"
                mixed_output_path = target_dir / f"{safe_stem}_dubbed.wav"
                mixed_path_str = mixer.mix(
                    original_path=bg_audio_path,
                    tts_path=str(tts_track_path),
                    output_path=str(mixed_output_path),
                    adjust_tts_volume=bool(opts.get("adjust_tts_volume", True)),
                    output_length=str(opts.get("output_length", "main")),
                )

                artifacts["take_cache"] = updated_cache
                artifacts["tts_track_path"] = str(tts_track_path)
                artifacts["mixed_audio_path"] = str(mixed_path_str)
                artifacts["dubbing"] = {
                    "tts_track_path": str(tts_track_path),
                    "mixed_audio_path": str(mixed_path_str),
                    "background_audio_path": bg_audio_path,
                    "assembly_id": assembly.get("id"),
                    "reused_take_count": reused_count,
                    "synthesized_take_count": synthesized_count,
                    "total_spoken_cues": len(spoken_cues),
                }

            completed = self.store.update_draft(
                draft_id,
                expected_revision=committing_record.revision,
                increment_revision=False,
                state="completed",
                artifacts=artifacts,
            )
            return completed.to_dict()
        except (AppValidationError, DraftConflictError):
            self.store.update_draft(draft_id, increment_revision=False, state="failed")
            raise
        except Exception as exc:
            self.store.update_draft(
                draft_id,
                increment_revision=False,
                state="failed",
                artifacts={**deepcopy(committing_record.artifacts), "last_error": str(exc)},
            )
            raise AppExecutionError(f"Failed to commit draft {draft_id}: {exc}") from exc


_draft_service: DraftSessionService | None = None
_service_lock = threading.Lock()


def get_draft_session_service() -> DraftSessionService:
    """Return the shared `DraftSessionService` instance."""
    global _draft_service
    if _draft_service is None:
        with _service_lock:
            if _draft_service is None:
                _draft_service = DraftSessionService()
    return _draft_service
