"""Optional ASMR timeline settings and time-aligned clone references."""
from __future__ import annotations

import hashlib
from io import BytesIO
import math
from pathlib import Path
from statistics import median
import subprocess
import tempfile


REMAKE_KEYS = ("reference_mode", "verify_with_asr", "max_retries", "min_similarity", "vc_refinement")
ACOUSTIC_CHOICES = {
    "binaural_mode": ("off", "static", "dynamic_hrtf"),
    "loudness_match": ("global", "per_cue"),
    "time_stretch_engine": ("ffmpeg_atempo", "pytsmod_wsola"),
}


def validate_timeline_options(options):
    for key in ("auto_clone", "auto_detect_delivery", "borrow_silence_slack", "duration_aware", "verify_with_asr"):
        if key in options and type(options[key]) is not bool:
            raise ValueError(f"{key} 必须是布尔值")
    if "max_atempo" in options:
        _number(options, "max_atempo", 1, math.inf)
    if options.get("reference_mode", "single") not in ("single", "per_style", "per_cue"):
        raise ValueError("reference_mode 必须是 single、per_style 或 per_cue")
    _integer(options, "max_retries", 0, 5)
    _number(options, "min_similarity", 0, 1)
    acoustic = options.get("acoustic_options", {})
    if not isinstance(acoustic, dict) or acoustic.keys() - {
        *ACOUSTIC_CHOICES, "eq_matching", "eq_strength", "reverb_match",
    }:
        raise ValueError("acoustic_options 包含未知声学设置")
    for key, choices in ACOUSTIC_CHOICES.items():
        if key in acoustic and acoustic[key] not in choices:
            raise ValueError(f"{key} 必须是 {'、'.join(choices)}")
    for key in ("eq_matching", "reverb_match"):
        if key in acoustic and type(acoustic[key]) is not bool:
            raise ValueError(f"{key} 必须是布尔值")
    _number(acoustic, "eq_strength", 0, 1)
    vc = options.get("vc_refinement", {})
    if (not isinstance(vc, dict) or vc.keys() - {"enabled", "provider", "diffusion_steps"}
            or type(vc.get("enabled", False)) is not bool
            or vc.get("provider", "seed_vc") != "seed_vc"):
        raise ValueError("vc_refinement 需要布尔 enabled 和 seed_vc 提供商")
    _integer(vc, "diffusion_steps", 1, 100)


def _number(options, key, low, high):
    if key in options:
        value = options[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} 超出可用范围")


def _integer(options, key, low, high):
    if key in options and (type(options[key]) is not int or not low <= options[key] <= high):
        raise ValueError(f"{key} 必须是 {low} 至 {high} 的整数")


def extract_voice_reference_candidate(audio_path, staging_dir, segments, *, prefer_speech=False):
    """Select highest RMS-to-noise-floor 6-10s clean window and write mono PCM_16 candidate."""
    import numpy as np
    import soundfile as sf
    from src.utils import get_ffmpeg

    # Decode via soundfile (or FFmpeg fallback for compressed containers) in blocks
    hop_sec = 0.1
    frame_rms: list[float] = []
    frame_clip: list[float] = []

    def _scan_stream(readable_path: Path) -> tuple[int, float]:
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
            return sr, stream.frames / sr

    decoded_temp_dir: tempfile.TemporaryDirectory[str] | None = None
    readable = audio_path
    try:
        try:
            sample_rate, total_duration = _scan_stream(readable)
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
            sample_rate, total_duration = _scan_stream(readable)

        if total_duration <= 0.1:
            raise ValueError("Audio track is too short for voice reference extraction")
        rms_arr = np.asarray(frame_rms, dtype=np.float64)
        clip_arr = np.asarray(frame_clip, dtype=np.float64)
        if len(rms_arr) == 0:
            raise ValueError("Audio stream contains no readable samples")

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

        coverage = None
        if prefer_speech and segments:
            speech_frames = np.zeros(len(rms_arr), dtype=bool)
            for segment in segments:
                left = max(0, math.floor(float(segment["start"]) / hop_sec))
                right = max(left, math.ceil(float(segment["end"]) / hop_sec))
                speech_frames[left:right] = True
            if speech_frames.any():
                coverage = np.r_[0, np.cumsum(speech_frames)]
        for w_start, w_end in candidate_intervals:
            i0 = max(0, int(math.floor(w_start / hop_sec)))
            i1 = min(len(rms_arr), max(i0 + 1, int(math.ceil(w_end / hop_sec))))
            if i1 <= i0 or (coverage is not None and coverage[i1] == coverage[i0]):
                continue
            sub_rms = rms_arr[i0:i1]
            sub_clip = clip_arr[i0:i1]
            speech_level = float(np.percentile(sub_rms, 80))
            local_noise = max(global_noise, float(np.percentile(sub_rms, 15)) + 1e-6)
            snr_db = 20.0 * math.log10(max(speech_level, 1e-7) / local_noise)
            clip_penalty = 50.0 * float(np.mean(sub_clip))
            dur = w_end - w_start
            dur_bonus = 2.0 if 6.0 <= dur <= 10.0 else 0.0
            score = snr_db + dur_bonus - clip_penalty
            if coverage is not None:
                score += 12.0 * (coverage[i1] - coverage[i0]) / (i1 - i0)
            if score > best_score:
                best_score = score
                best_window = (w_start, w_end)
                best_snr_db = snr_db
                best_rms = float(np.sqrt(np.mean(np.square(sub_rms))))

        ref_start, ref_end = best_window
        staging_dir.mkdir(parents=True, exist_ok=True)
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


def prepare_references(source, cues, mode, directory, *, language="ja", require_transcript=True, match_level=False):
    """Choose whole transcript spans so the recorded prompt and text stay aligned."""
    import numpy as np
    import soundfile as sf

    directory = Path(directory)
    styles = [cue.get("delivery") or "normal" for cue in cues]
    groups = styles
    if match_level:
        levels = [cue.get("source_rms_db") for cue in cues]
        by_style = {}
        for style, level in zip(styles, levels, strict=True):
            if level is not None and math.isfinite(level):
                by_style.setdefault(style, []).append(level)
        midpoints = {}
        for style, values in by_style.items():
            quiet, loud = min(values), max(values)
            if loud - quiet >= 6:
                center = median(values)
                midpoints[style] = center if center > quiet else (quiet + loud) / 2
        groups = [(style, level >= midpoints[style]) if style in midpoints and level is not None
                  and math.isfinite(level) else style for style, level in zip(styles, levels, strict=True)]
    texts = [str(cue.get("original") or cue.get("source_text") or "").strip() for cue in cues]
    times = [(float(cue["start_time"]), float(cue["end_time"])) for cue in cues]
    assets, selected = {}, {}

    with sf.SoundFile(source) as stream:
        rate = stream.samplerate
        candidates = {}
        for index, ((start, end), text) in enumerate(zip(times, texts, strict=True)):
            limit = 10 if mode == "per_style" else 8
            if ((require_transcript and not text) or not 0 < end - start <= limit
                    or start < 0 or end > stream.frames / rate):
                continue
            if ((index > 0 and times[index - 1][1] > start + .03)
                    or (index + 1 < len(times) and times[index + 1][0] < end - .03)):
                continue
            first, last = index, index
            target = 5 if mode == "per_style" else 4
            while times[last][1] - times[first][0] < target:
                neighbors = []
                if (first > 0 and (texts[first - 1] or not require_transcript) and groups[first - 1] == groups[index]
                        and 0 <= times[first][0] - times[first - 1][1] <= .75):
                    neighbors.append((first - 1, last))
                if (last + 1 < len(times) and (texts[last + 1] or not require_transcript)
                        and groups[last + 1] == groups[index]
                        and 0 <= times[last + 1][0] - times[last][1] <= .75):
                    neighbors.append((first, last + 1))
                neighbors = [pair for pair in neighbors if
                             times[pair[1]][1] - times[pair[0]][0] <= limit]
                if not neighbors:
                    break
                first, last = min(neighbors, key=lambda pair: times[pair[1]][1] - times[pair[0]][0])
            left, right = round(times[first][0] * rate), round(times[last][1] * rate)
            minimum_duration = 2 if match_level else .5
            if not 0 <= left < right <= stream.frames or (right - left) / rate < minimum_duration:
                continue
            stream.seek(left)
            clip = stream.read(right - left, dtype="float32", always_2d=True)
            if not np.isfinite(clip).all() or np.max(np.abs(clip)) < .0001:
                continue
            window = max(1, round(rate * .02))
            samples = clip[:len(clip) // window * window]
            if not len(samples):
                continue
            levels = np.sqrt(np.mean(samples.reshape(-1, window, clip.shape[1]) ** 2, axis=(1, 2)))
            floor, active = np.percentile(levels, [15, 85])
            quality = float(20 * np.log10((active + .0001) / (floor + .0001)))
            quality -= 20 * float(np.mean(np.abs(clip) >= .995))
            candidates[index] = (first, last, quality, (right - left) / rate)

        best = {}
        for index, candidate in candidates.items():
            rank = (candidate[3] >= 5, candidate[2])
            for group in {styles[index], groups[index]}:
                if group not in best or rank > best[group][0]:
                    best[group] = rank, candidate

        saved = {}
        for index, style in enumerate(styles):
            match = candidates.get(index) if mode == "per_cue" else None
            if match is None:
                _, match = best.get(groups[index], best.get(style, (None, None)))
            if match is None:
                continue
            first, last = match[:2]
            span = (first, last)
            if span not in saved:
                left, right = round(times[first][0] * rate), round(times[last][1] * rate)
                stream.seek(left)
                buffer = BytesIO()
                sf.write(buffer, stream.read(right - left, dtype="float32", always_2d=True),
                         rate, format="WAV", subtype="PCM_24")
                data = buffer.getvalue()
                digest = hashlib.sha256(data).hexdigest()
                transcript = " ".join(text for text in texts[first:last + 1] if text)
                ref_id = "cue-" + hashlib.sha256(f"{digest}:{language}:{transcript}".encode()).hexdigest()
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"{ref_id}.wav"
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    from uuid import uuid4
                    temporary = directory / f"{uuid4().hex}.pending.wav"
                    try:
                        temporary.write_bytes(data)
                        temporary.replace(path)
                    finally:
                        temporary.unlink(missing_ok=True)
                assets[ref_id] = {"path": str(path.resolve()), "sha256": digest,
                                  "transcript": transcript, "language": language}
                saved[span] = ref_id
            selected[index] = saved[span]
    return assets, selected
