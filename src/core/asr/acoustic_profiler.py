"""Measure cue-level vocal delivery and reference level without an ASR model."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal, stats


def cue_bounds(segment) -> tuple[float, float]:
    """Read the timestamps used by ASR segments and speech timelines."""
    if isinstance(segment, Mapping):
        start = segment.get("start_time", segment.get("start"))
        end = segment.get("end_time", segment.get("end"))
    else:
        start = getattr(segment, "start_time", getattr(segment, "start", None))
        end = getattr(segment, "end_time", getattr(segment, "end", None))
    if start is None or end is None:
        return 0.0, 0.0
    start, end = float(start), float(end)
    return (start, end) if math.isfinite(start) and math.isfinite(end) else (0.0, 0.0)


def active_rms_db(audio: np.ndarray, sr: int) -> float | None:
    """Return RMS over active 20 ms blocks, in dBFS, or None for silence."""
    if not audio.size:
        return None
    block = max(1, round(0.020 * sr))
    power = np.square(audio, dtype=np.float64)
    if power.ndim == 2:
        power = power.mean(axis=1)
    bounds = np.arange(0, len(power), block)
    counts = np.diff(np.append(bounds, len(power)))
    energies = np.add.reduceat(power, bounds) / counts
    peak = float(energies.max())
    if peak <= 1e-10:
        return None
    active = energies >= max(1e-10, peak * 0.01)
    return float(10 * np.log10(np.average(energies[active], weights=counts[active])))


def _voicing(audio: np.ndarray, sr: int) -> float:
    frame = max(1, round(0.04 * sr))
    if len(audio) < frame:
        return 0.0
    hop = max(1, frame // 2)
    windows = np.lib.stride_tricks.sliding_window_view(audio, frame)[::hop]
    starts = np.arange(len(windows)) * hop
    cumulative = np.r_[0.0, np.cumsum(np.square(audio, dtype=np.float64))]
    energy = (cumulative[starts + frame] - cumulative[starts]) / frame
    active = np.flatnonzero(energy >= max(1e-10, float(energy.max()) * 0.02))
    if not len(active):
        return 0.0
    # Sample long cues uniformly to bound memory without favoring their onset.
    selected = np.linspace(0, len(active) - 1, min(len(active), 256), dtype=int)
    active = windows[active[selected]]
    active = (active - active.mean(axis=1, keepdims=True)) * np.hanning(frame)
    fft_size = 2 ** (2 * frame - 1).bit_length()
    spectrum = np.fft.rfft(active, n=fft_size)
    acf = np.fft.irfft(np.abs(spectrum) ** 2, n=fft_size)
    first = max(1, round(sr / 500))
    last = min(frame - 1, round(sr / 65))
    if last < first:
        return 0.0
    scores = acf[:, first : last + 1].max(axis=1) / np.maximum(acf[:, 0], 1e-12)
    return float(np.clip(np.median(scores), 0, 1))


def profile_cues(vocals_path: str | Path, segments) -> list[dict]:
    """Return one delivery suggestion and set of acoustic measurements per cue."""
    profiles = []
    with sf.SoundFile(vocals_path) as source:
        for segment in segments:
            start, end = cue_bounds(segment)
            first = min(source.frames, max(0, round(start * source.samplerate)))
            last = min(source.frames, max(first, round(end * source.samplerate)))
            source.seek(first)
            audio = source.read(last - first, dtype="float32", always_2d=True)
            audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
            rms_db = active_rms_db(audio, source.samplerate)
            profile = {
                "delivery": "normal",
                "source_rms_db": rms_db,
                "source_rms_percentile": None,
                "voicing": None,
                "spectral_centroid_hz": None,
                "high_frequency_ratio": None,
            }
            profiles.append(profile)
            if rms_db is None or len(audio) < round(0.04 * source.samplerate):
                continue
            # Use the strongest channel to avoid cancellation in binaural recordings.
            voiced_audio = audio[:, np.square(audio, dtype=np.float64).mean(axis=0).argmax()]
            frequencies, power = signal.welch(
                voiced_audio, fs=source.samplerate, nperseg=min(len(audio), 2048)
            )
            total = max(float(power.sum()), np.finfo(float).tiny)
            profile.update(
                voicing=_voicing(voiced_audio, source.samplerate),
                spectral_centroid_hz=float(frequencies @ power / total),
                high_frequency_ratio=float(power[frequencies > 3000].sum() / total),
            )

    measured = [profile for profile in profiles if profile["source_rms_db"] is not None]
    if measured:
        levels = [profile["source_rms_db"] for profile in measured]
        percentiles = (stats.rankdata(levels, method="average") - 0.5) / len(levels)
        reference_level = float(np.median(levels))
        for profile, percentile in zip(measured, percentiles, strict=True):
            profile["source_rms_percentile"] = float(percentile)
            voicing = profile["voicing"]
            if voicing is None:
                continue
            if voicing < 0.30 and (
                profile["high_frequency_ratio"] >= 0.18
                or profile["spectral_centroid_hz"] >= 1800
            ):
                profile["delivery"] = "whisper"
            elif profile["source_rms_db"] < -29 or (
                percentile < 0.40 and profile["source_rms_db"] < reference_level - 4
            ):
                profile["delivery"] = "soft"
    return profiles


def annotate_delivery(audio_path, cues, *, overwrite=False):
    """Attach delivery hints without changing cue text or timing."""
    annotated = []
    for cue, profile in zip(cues, profile_cues(audio_path, cues), strict=True):
        item = {**cue, "source_rms_db": profile["source_rms_db"]}
        if overwrite or not item.get("delivery") or item.get("auto_delivery"):
            item.update(delivery=profile["delivery"], auto_delivery=True)
        annotated.append(item)
    return annotated
