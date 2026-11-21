"""Acoustic pre-ASR VAD slicer for long ASMR recordings.

Pure NumPy/SciPy short-time RMS and noise-floor adaptive valley detector so
long-form Whisper models never merge utterances across multi-second silence
gaps or drift on continuous monologues exceeding ``max_chunk_sec``.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import uniform_filter1d


def slice_speech_regions(
    audio_16k: np.ndarray,
    sample_rate: int = 16000,
    *,
    min_silence_sec: float = 0.65,
    max_chunk_sec: float = 25.0,
    pad_sec: float = 0.15,
    energy_threshold_db: float = -42.0,
) -> list[tuple[float, float]]:
    """Slice ``audio_16k`` into ``(start_sec, end_sec)`` speech regions.

    - Splits across silence/low-energy valleys ``>= min_silence_sec``.
    - Adapts to elevated background floors while still handling clean silence
      and continuous monologues.
    - Subdivides any speech region longer than ``max_chunk_sec`` at the
      quietest local acoustic valley so every returned span is ``<= max_chunk_sec``.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not math.isfinite(min_silence_sec) or min_silence_sec <= 0:
        raise ValueError("min_silence_sec must be positive")
    if not math.isfinite(max_chunk_sec) or max_chunk_sec <= 0:
        raise ValueError("max_chunk_sec must be positive")
    if not math.isfinite(pad_sec) or pad_sec < 0:
        raise ValueError("pad_sec must be non-negative")
    if not math.isfinite(energy_threshold_db):
        raise ValueError("energy_threshold_db must be finite")

    audio = np.asarray(audio_16k, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=-1, dtype=np.float32)
    elif audio.ndim != 1:
        audio = audio.reshape(-1)

    if audio.size == 0:
        return []

    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    total_samples = int(audio.shape[0])
    total_duration = total_samples / float(sample_rate)
    if total_duration <= 0.0:
        return []

    hop_samples = min(total_samples, max(1, round(0.02 * sample_rate)))
    frame_sec = hop_samples / float(sample_rate)
    full_frames = total_samples // hop_samples

    if full_frames > 0:
        sq = np.square(audio[: full_frames * hop_samples], dtype=np.float64).reshape(
            full_frames, hop_samples
        )
        means = sq.mean(axis=1)
        remainder = total_samples - full_frames * hop_samples
        if remainder > 0:
            tail_mean = float(
                np.mean(np.square(audio[full_frames * hop_samples :], dtype=np.float64))
            )
            means = np.concatenate([means, np.array([tail_mean], dtype=np.float64)])
    else:
        means = np.array([float(np.mean(np.square(audio, dtype=np.float64)))], dtype=np.float64)

    n_frames = int(means.shape[0])
    smooth_win = min(3, n_frames)
    smoothed_means = (
        uniform_filter1d(means, size=smooth_win, mode="nearest") if smooth_win > 1 else means
    )
    frame_rms = np.sqrt(np.maximum(smoothed_means, 0.0))
    frame_db = 20.0 * np.log10(np.maximum(frame_rms, 1e-10))

    dead_air_db = min(energy_threshold_db - 20.0, -65.0)
    max_db = float(np.max(frame_db))
    if max_db <= dead_air_db:
        return []

    noise_floor_db = float(np.percentile(frame_db, 15))
    dynamic_range = max_db - noise_floor_db
    if dynamic_range >= 12.0:
        thresh_db = max(
            energy_threshold_db,
            noise_floor_db + min(8.0, 0.35 * dynamic_range),
        )
        thresh_db = min(thresh_db, max_db - 6.0)
    else:
        thresh_db = energy_threshold_db

    active = frame_db >= thresh_db
    if not np.any(active):
        return []

    # Extract contiguous active frame runs [start_frame, end_frame).
    padded_active = np.empty(n_frames + 2, dtype=bool)
    padded_active[0] = False
    padded_active[1:-1] = active
    padded_active[-1] = False
    transitions = np.flatnonzero(padded_active[1:] != padded_active[:-1])
    raw_runs: list[tuple[int, int]] = [
        (int(transitions[idx]), int(transitions[idx + 1]))
        for idx in range(0, len(transitions), 2)
    ]

    if len(raw_runs) > 1:
        filtered = [run for run in raw_runs if (run[1] - run[0]) * frame_sec >= 0.03]
        if filtered:
            raw_runs = filtered

    # Merge runs separated by silences strictly shorter than min_silence_sec.
    merged_runs: list[tuple[int, int]] = [raw_runs[0]]
    for start_f, end_f in raw_runs[1:]:
        prev_start_f, prev_end_f = merged_runs[-1]
        gap_sec = (start_f - prev_end_f) * frame_sec
        if gap_sec < min_silence_sec:
            merged_runs[-1] = (prev_start_f, end_f)
        else:
            merged_runs.append((start_f, end_f))

    raw_times = [
        (start_f * frame_sec, min(total_duration, end_f * frame_sec))
        for start_f, end_f in merged_runs
    ]

    # Apply pad_sec while preventing overlap across adjacent regions.
    padded_regions: list[tuple[float, float]] = []
    for idx, (raw_start, raw_end) in enumerate(raw_times):
        left_limit = 0.0 if idx == 0 else 0.5 * (raw_times[idx - 1][1] + raw_start)
        right_limit = (
            total_duration if idx == len(raw_times) - 1 else 0.5 * (raw_end + raw_times[idx + 1][0])
        )
        p_start = max(left_limit, raw_start - pad_sec)
        p_end = min(right_limit, raw_end + pad_sec)
        if p_end > p_start:
            padded_regions.append((p_start, p_end))

    # Subdivide any region longer than max_chunk_sec at the quietest local valley.
    valley_win = max(1, round(0.12 / frame_sec))
    valley_score = (
        uniform_filter1d(frame_rms, size=min(valley_win, n_frames), mode="nearest")
        if n_frames > 1
        else frame_rms
    )

    final_regions: list[tuple[float, float]] = []
    for reg_start, reg_end in padded_regions:
        cur_start = reg_start
        while reg_end - cur_start > max_chunk_sec + 1e-9:
            min_offset = max_chunk_sec * 0.25
            lo_sec = cur_start + min_offset
            hi_sec = cur_start + max_chunk_sec
            lo_f = max(int(math.ceil(lo_sec / frame_sec)), int(cur_start / frame_sec) + 1)
            hi_f = min(n_frames - 1, int(math.floor(hi_sec / frame_sec)))
            if hi_f >= lo_f:
                best_f = lo_f + int(np.argmin(valley_score[lo_f : hi_f + 1]))
                split_sec = best_f * frame_sec
                split_sec = min(cur_start + max_chunk_sec, max(cur_start + 1e-3, split_sec))
            else:
                split_sec = cur_start + max_chunk_sec
            final_regions.append((round(cur_start, 6), round(split_sec, 6)))
            cur_start = split_sec

        if reg_end - cur_start > 1e-4:
            final_regions.append((round(cur_start, 6), round(reg_end, 6)))

    return final_regions
