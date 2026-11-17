"""ASMR binaural panning estimation, constant-power stereo mapping, and silence slack planning."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


def estimate_cue_panning(
    stereo_audio_path: str | Path,
    start_sec: float,
    end_sec: float,
) -> float:
    """Estimate smooth Left/Right binaural pan in ``[-0.95, 0.95]`` for ``[start_sec, end_sec]``.

    Stream-reads only the requested cue slice via ``sf.SoundFile.seek`` + ``read``
    (``O(cue_length)`` I/O, bounded block memory). Returns ``0.0`` for mono audio,
    empty/invalid intervals, or silent cues.

    Convention: ``-1.0`` = hard left ear, ``0.0`` = center, ``+1.0`` = hard right ear.
    """
    if not (math.isfinite(start_sec) and math.isfinite(end_sec)):
        return 0.0
    start_clamped = max(0.0, float(start_sec))
    end_clamped = float(end_sec)
    if end_clamped <= start_clamped:
        return 0.0

    with sf.SoundFile(str(stereo_audio_path)) as audio:
        if audio.channels < 2 or audio.frames <= 0 or audio.samplerate <= 0:
            return 0.0

        first_frame = max(0, min(audio.frames, round(start_clamped * audio.samplerate)))
        last_frame = max(first_frame, min(audio.frames, round(end_clamped * audio.samplerate)))
        remaining = last_frame - first_frame
        if remaining <= 0:
            return 0.0

        audio.seek(first_frame)
        subframe_len = max(1, round(0.02 * audio.samplerate))
        block_size = max(subframe_len, min(65536, subframe_len * 200))

        sub_sq_l: list[np.ndarray] = []
        sub_sq_r: list[np.ndarray] = []

        while remaining > 0:
            to_read = min(block_size, remaining)
            block = audio.read(to_read, dtype="float32", always_2d=True)
            read_count = int(block.shape[0])
            if read_count <= 0:
                break
            remaining -= read_count

            lr = np.nan_to_num(block[:, :2], nan=0.0, posinf=0.0, neginf=0.0)
            sq = np.square(lr, dtype=np.float64)

            full = read_count // subframe_len
            if full > 0:
                reshaped = sq[: full * subframe_len].reshape(full, subframe_len, 2)
                means = reshaped.mean(axis=1)
                sub_sq_l.append(means[:, 0])
                sub_sq_r.append(means[:, 1])
            rem_samples = read_count - full * subframe_len
            if rem_samples > 0:
                tail_mean = sq[full * subframe_len :].mean(axis=0)
                sub_sq_l.append(np.array([tail_mean[0]], dtype=np.float64))
                sub_sq_r.append(np.array([tail_mean[1]], dtype=np.float64))

    if not sub_sq_l:
        return 0.0

    arr_l = np.concatenate(sub_sq_l)
    arr_r = np.concatenate(sub_sq_r)
    frame_energy = 0.5 * (arr_l + arr_r)
    max_energy = float(np.max(frame_energy))
    if max_energy <= 1e-12:
        return 0.0

    # Gate out silence and quiet center room-tone so active speech frames govern ILD.
    gate = max(1e-8, max_energy * 0.05)
    active = frame_energy >= gate
    if not np.any(active):
        active = frame_energy > 0.0

    rms_l = math.sqrt(float(np.mean(arr_l[active])))
    rms_r = math.sqrt(float(np.mean(arr_r[active])))
    denom = rms_r + rms_l
    if denom <= 1e-12:
        return 0.0

    pan = (rms_r - rms_l) / denom
    return float(max(-0.95, min(0.95, pan)))


def pan_mono_to_stereo(samples: np.ndarray, pan: float) -> np.ndarray:
    """Convert a 1D mono (or 2D) take into ``(N, 2)`` float32 stereo using constant-power panning.

    Uses ``theta = (pan + 1.0) * pi / 4``, ``gain_L = cos(theta) * sqrt(2)``,
    ``gain_R = sin(theta) * sqrt(2)`` so ``pan = 0.0`` produces ``(1.0, 1.0)``
    gains matching legacy dual-mono amplitude.
    """
    if not math.isfinite(pan):
        raise ValueError("pan must be finite")

    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        mono = arr
    elif arr.ndim == 2:
        mono = (
            arr.mean(axis=1, dtype=np.float32)
            if arr.shape[1] > 0
            else np.zeros(arr.shape[0], dtype=np.float32)
        )
    else:
        raise ValueError("samples must be a 1D or 2D audio array")

    clamped_pan = max(-1.0, min(1.0, float(pan)))
    theta = (clamped_pan + 1.0) * (math.pi / 4.0)
    scale = math.sqrt(2.0)
    gain_l = np.float32(math.cos(theta) * scale)
    gain_r = np.float32(math.sin(theta) * scale)

    stereo = np.empty((mono.shape[0], 2), dtype=np.float32)
    stereo[:, 0] = mono * gain_l
    stereo[:, 1] = mono * gain_r
    return stereo


def _cue_bounds(cue: dict[str, Any]) -> tuple[float, float, float]:
    if "start_time" in cue:
        start = float(cue["start_time"])
    elif "start" in cue:
        start = float(cue["start"])
    else:
        raise KeyError("timeline cue requires 'start_time' or 'start'")

    if "end_time" in cue:
        end = float(cue["end_time"])
    elif "end" in cue:
        end = float(cue["end"])
    else:
        raise KeyError("timeline cue requires 'end_time' or 'end'")

    if "pause_sec" in cue:
        pause_sec = float(cue["pause_sec"])
    elif "pause_ms" in cue:
        pause_sec = float(cue["pause_ms"]) / 1000.0
    else:
        pause_sec = 0.0

    if not (math.isfinite(start) and math.isfinite(end) and math.isfinite(pause_sec)):
        raise ValueError("timeline cue bounds must be finite")
    if pause_sec < 0.0:
        raise ValueError("pause_sec must be non-negative")
    return start, end, pause_sec


def plan_cue_slots(
    timeline: list[dict[str, Any]],
    take_durations: list[float],
    *,
    reference_duration: float | None = None,
    guard_sec: float = 0.06,
    max_atempo: float | None = 1.35,
    cap_atempo: bool = True,
) -> list[dict[str, Any]]:
    """Plan effective cue durations by borrowing post-cue inter-line silent slack first."""
    if len(timeline) != len(take_durations):
        raise ValueError("timeline and take_durations must have the same length")
    if not math.isfinite(guard_sec) or guard_sec < 0.0:
        raise ValueError("guard_sec must be non-negative and finite")
    if max_atempo is not None and (not math.isfinite(max_atempo) or max_atempo < 1.0):
        raise ValueError("max_atempo must be >= 1.0 when provided")

    n_cues = len(timeline)
    if n_cues == 0:
        return []

    bounds = [_cue_bounds(cue) for cue in timeline]
    threshold = 1.35 if max_atempo is None else float(max_atempo)
    should_cap = bool(cap_atempo and max_atempo is not None)

    plans: list[dict[str, Any]] = []
    for idx, ((start, end, pause_sec), raw_dur) in enumerate(zip(bounds, take_durations, strict=True)):
        take_dur = float(raw_dur)
        if not math.isfinite(take_dur) or take_dur < 0.0:
            raise ValueError("take_duration must be non-negative and finite")

        natural_slot = end - start - pause_sec
        if natural_slot <= 0.0:
            raise ValueError("cue natural slot duration must be positive")

        if idx + 1 < n_cues:
            next_start = bounds[idx + 1][0]
            available_slack = max(0.0, (next_start - guard_sec) - end)
        elif (
            reference_duration is not None
            and math.isfinite(reference_duration)
            and reference_duration > 0.0
        ):
            available_slack = max(0.0, float(reference_duration) - end - pause_sec)
        else:
            available_slack = 0.0

        borrowed_sec = (
            min(take_dur - natural_slot, available_slack)
            if take_dur > natural_slot
            else 0.0
        )
        effective_slot = natural_slot + borrowed_sec
        required_atempo = max(1.0, take_dur / effective_slot)
        over_speed = bool(required_atempo > threshold + 1e-9)
        applied_atempo = min(required_atempo, threshold) if should_cap else required_atempo

        entry: dict[str, Any] = {
            "index": idx,
            "start_time": start,
            "end_time": end,
            "effective_end_time": end + borrowed_sec,
            "natural_slot": natural_slot,
            "available_slack": available_slack,
            "borrowed_sec": borrowed_sec,
            "effective_slot": effective_slot,
            "take_duration": take_dur,
            "required_atempo": required_atempo,
            "applied_atempo": applied_atempo,
            "over_speed": over_speed,
        }
        cue_id = timeline[idx].get("segment_id") or timeline[idx].get("id")
        if cue_id is not None:
            entry["segment_id"] = cue_id
        plans.append(entry)

    return plans
