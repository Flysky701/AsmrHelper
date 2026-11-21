"""Fill quiet separation holes with low-level room tone from nearby speech gaps."""

from __future__ import annotations

from math import gcd
from pathlib import Path
from uuid import uuid4

import numpy as np
from scipy import signal

from src.core.asr.acoustic_profiler import cue_bounds


def _find_room_tone(
    source: np.ndarray, sr: int, intervals: list[tuple[float, float]]
) -> list[tuple[float, float, int, int]]:
    guard = round(sr * 0.035)
    window = max(1, round(sr * 0.240))
    minimum = max(1, round(sr * 0.100))
    rooms = []
    end = 0
    for start_seconds, end_seconds in [*intervals, (len(source) / sr, len(source) / sr)]:
        start = min(len(source), max(0, round(start_seconds * sr)))
        gap_start = end + (guard if end else 0)
        gap_end = start - guard
        for offset in range(gap_start, gap_end - minimum + 1, window):
            limit = min(gap_end, offset + window)
            clip = source[offset:limit]
            clip = clip - clip.mean(axis=0)
            block_rms = [
                float(np.sqrt(np.mean(np.square(clip[index : index + minimum], dtype=np.float64))))
                for index in range(0, len(clip), minimum)
            ]
            quietest, loudest = min(block_rms), max(block_rms)
            # Reject digital silence, transients, and unmistakably loud source gaps.
            if loudest > 1e-6 and loudest < 0.02 and quietest >= loudest * 0.4:
                rooms.append(((offset + limit) / (2 * sr), loudest, offset, limit))
        end = max(end, min(len(source), round(end_seconds * sr)))
    return rooms


def _loop(clip: np.ndarray, length: int, fade_samples: int) -> np.ndarray:
    result = np.empty((length,) + clip.shape[1:], dtype=clip.dtype)
    fade = min(len(clip) // 3, fade_samples)
    first = min(length, len(clip))
    result[:first] = clip[:first]
    envelope = np.linspace(0, 1, fade) if clip.ndim == 1 else np.linspace(0, 1, fade)[:, None]
    end = first
    while end < length:
        start = end - fade
        count = min(len(clip), length - start)
        if fade:
            result[start:end] = result[start:end] * (1 - envelope) + clip[:fade] * envelope
        result[end : start + count] = clip[fade:count]
        end = start + count
    return result


def inpaint_room_tone(
    background: np.ndarray,
    sr: int,
    source: np.ndarray,
    source_sr: int,
    segments,
) -> np.ndarray:
    """Crossfade source room tone into sustained quiet areas, without changing sample rate."""
    if not background.size or not source.size:
        return background
    intervals = sorted((start, end) for start, end in map(cue_bounds, segments) if end > start)
    if not intervals:
        return background
    source = np.nan_to_num(source, nan=0.0, posinf=0.0, neginf=0.0)
    rooms = _find_room_tone(source, source_sr, intervals)
    if not rooms:
        return background
    typical = float(np.percentile([room[1] for room in rooms], 35))
    rooms = [room for room in rooms if room[1] <= typical * 2]
    result = background
    fade_samples = max(1, round(sr * 0.030))
    block = max(1, round(sr * 0.020))
    previous_end = 0
    for start_seconds, end_seconds in intervals:
        start = min(len(background), max(previous_end, round(start_seconds * sr)))
        end = min(len(background), round(end_seconds * sr))
        if end <= start:
            continue
        previous_end = end
        clip = background[start:end]
        _, level, tone_start, tone_end = min(
            rooms, key=lambda room: abs(room[0] - (start_seconds + end_seconds) / 2)
        )
        tone = source[tone_start:tone_end]
        tone = tone - tone.mean(axis=0)
        if source_sr != sr:
            divisor = gcd(source_sr, sr)
            tone = signal.resample_poly(tone, sr // divisor, source_sr // divisor, axis=0)
        if clip.ndim == 1 and tone.ndim == 2:
            tone = tone.mean(axis=1)
        if clip.ndim == 2:
            tone = tone.reshape(len(tone), -1)
            if tone.shape[1] != clip.shape[1]:
                tone = np.repeat(tone.mean(axis=1, keepdims=True), clip.shape[1], axis=1)
        boundaries = np.arange(0, len(clip), block)
        power = np.square(clip, dtype=np.float64)
        if power.ndim == 2:
            power = power.mean(axis=1)
        energies = np.add.reduceat(power, boundaries) / np.diff(np.append(boundaries, len(clip)))
        quiet = energies < (level * 0.42) ** 2
        transitions = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
        for first, last in transitions.reshape(-1, 2):
            low = first * block
            high = min(len(clip), last * block)
            length = high - low
            if length < 2 * fade_samples:
                continue
            bed = _loop(tone, length, fade_samples)
            ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade_samples))
            envelope = np.full(length, 0.65)
            envelope[:fade_samples] *= ramp
            envelope[-fade_samples:] *= ramp[::-1]
            if bed.ndim == 2:
                envelope = envelope[:, None]
            if result is background:
                result = background.copy()
            result[start + low : start + high] += bed * envelope
    return result


def prepare_room_tone_bed(background_path, original_path, segments, directory) -> str:
    """Create a task-local float WAV when a pure-replacement bed needs filling."""
    from src.mixer.multitrack import _load_audio, _write_audio

    if not segments:
        return str(background_path)
    source, source_sr = _load_audio(original_path)
    background, background_sr = _load_audio(background_path)
    if background_sr != source_sr:
        divisor = gcd(background_sr, source_sr)
        background = signal.resample_poly(
            background, source_sr // divisor, background_sr // divisor, axis=0
        )
    bed = inpaint_room_tone(background, source_sr, source, source_sr, segments)
    if bed is background and background_sr == source_sr:
        return str(background_path)
    path = Path(directory) / f"room-tone-{uuid4().hex}.wav"
    _write_audio(path, bed, source_sr)
    return str(path)
