"""Optional cue processors for matching synthesized speech to a reference."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy import signal

from src.core.asr.acoustic_profiler import active_rms_db
from src.mixer.binaural import pan_mono_to_stereo


@dataclass(frozen=True)
class CueContext:
    reference: np.ndarray | None
    reference_sr: int
    options: Mapping


def _mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def match_loudness(audio: np.ndarray, sr: int, context: CueContext) -> np.ndarray:
    if context.options.get("loudness_match") != "per_cue" or context.reference is None:
        return audio
    source_db = active_rms_db(context.reference, context.reference_sr)
    take_db = active_rms_db(audio, sr)
    if source_db is None or take_db is None:
        return audio
    gain = 10 ** (float(np.clip(source_db - take_db, -15, 9)) / 20)
    peak = float(np.max(np.abs(audio)))
    gain = min(gain, 0.97 / peak)
    # Leave a short ramp at each cue boundary when changing scalar gain.
    edge = min(len(audio) // 2, max(1, round(sr * 0.008)))
    envelope = np.full(len(audio), gain)
    if edge:
        boundary_gain = min(1.0, 0.97 / peak)
        fade = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, edge))
        envelope[:edge] = boundary_gain + (gain - boundary_gain) * fade
        envelope[-edge:] = envelope[:edge][::-1]
    return audio * (envelope[:, None] if audio.ndim == 2 else envelope)


def _band_levels(audio: np.ndarray, sr: int, centers: np.ndarray) -> np.ndarray:
    # Average channel powers to preserve frequencies common in binaural references.
    freq, power = signal.welch(audio, fs=sr, nperseg=min(len(audio), 4096), axis=0)
    if power.ndim == 2:
        power = power.mean(axis=1)
    floor = max(float(power.max()) * 1e-6, np.finfo(float).tiny)
    levels = []
    for center in centers:
        in_band = (freq >= center / 2 ** (1 / 6)) & (freq < center * 2 ** (1 / 6))
        level = power[in_band].mean() if in_band.any() else np.interp(center, freq, power)
        levels.append(10 * np.log10(max(float(level), floor)))
    return np.asarray(levels)


def match_eq(audio: np.ndarray, sr: int, context: CueContext) -> np.ndarray:
    if not context.options.get("eq_matching") or context.reference is None:
        return audio
    strength = float(np.clip(float(context.options.get("eq_strength", 1.0)), 0, 1))
    if not strength:
        return audio
    source = context.reference
    source_sr = context.reference_sr
    max_frequency = min(sr, source_sr) * 0.43
    if min(len(source), len(audio)) < 64 or max_frequency < 400:
        return audio
    if active_rms_db(source, source_sr) is None or active_rms_db(audio, sr) is None:
        return audio
    centers = 125 * 2 ** (np.arange(32) / 3)
    centers = centers[centers <= max_frequency]
    correction = _band_levels(source, source_sr, centers) - _band_levels(audio, sr, centers)
    midrange = (centers >= 250) & (centers <= 3000)
    correction -= np.median(correction[midrange])
    # Prevent large narrow boosts and favor de-essing when the reference is darker.
    sibilance = (centers >= 5000) & (centers <= 8000)
    correction[sibilance] = np.minimum(correction[sibilance], 0)
    correction = np.clip(correction, -9, 6) * strength
    normalized = np.r_[0, centers / (sr / 2), 1]
    gains = 10 ** (np.r_[correction[0], correction, 0] / 20)
    linear_fir = signal.firwin2(257, normalized, gains**2)
    minimum_fir = signal.minimum_phase(linear_fir)
    return signal.lfilter(minimum_fir, [1.0], audio, axis=0)


def match_binaural(audio: np.ndarray, sr: int, context: CueContext) -> np.ndarray:
    mode = context.options.get("binaural_mode")
    if mode == "off":
        return _mono(audio)
    source = context.reference
    if (
        mode not in ("static", "dynamic_hrtf")
        or source is None
        or source.ndim != 2
        or source.shape[1] < 2
        or not len(source)
    ):
        return audio
    power = np.square(source[:, :2], dtype=np.float64)
    window = max(1, round(context.reference_sr * 0.075))
    hop = max(1, window // 2)
    positions = np.arange(0, len(source), hop)
    cumulative = np.vstack(([0.0, 0.0], np.cumsum(power, axis=0)))
    first = np.maximum(0, positions - window // 2)
    last = np.minimum(len(source), positions + (window + 1) // 2)
    mean_power = (cumulative[last] - cumulative[first]) / (last - first)[:, None]
    mean_power = np.maximum(mean_power, 0)
    energy = mean_power.mean(axis=1)
    active = energy >= max(1e-10, float(energy.max()) * 0.02)
    if not active.any():
        return pan_mono_to_stereo(audio, 0.0)
    if mode == "static":
        left, right = np.sqrt(mean_power[active].mean(axis=0))
        return pan_mono_to_stereo(audio, float(np.clip((right - left) / (right + left), -0.95, 0.95)))
    left, right = np.sqrt(mean_power[active]).T
    pan = np.clip((right - left) / (right + left), -0.95, 0.95)
    timeline = np.linspace(0, len(source) - 1, len(audio))
    pan = np.interp(timeline, positions[active], pan)
    mono = _mono(audio)
    samples = np.arange(len(mono))
    # A variable fractional delay and head shadow are applied to the far ear.
    cutoff = min(5000.0, sr * 0.42)
    shadow = signal.sosfilt(signal.butter(1, cutoff, fs=sr, output="sos"), mono)
    stereo = []
    for side in (-1, 1):
        far = np.maximum(0, -side * pan)
        delay = far * (sr * 0.0006 / 0.95)
        dry = np.interp(samples - delay, samples, mono, left=0.0)
        shaded = np.interp(samples - delay, samples, shadow, left=0.0)
        gain = np.sqrt(2) * np.cos((1 - side * pan) * np.pi / 4)
        stereo.append(gain * (dry + far * (shaded - dry)))
    return np.column_stack(stereo)


def match_reverb(audio: np.ndarray, sr: int, context: CueContext) -> np.ndarray:
    if not context.options.get("reverb_match"):
        return audio
    # A short, damped early-reflection pattern models a small near-field room.
    cutoff = min(5500.0, sr * 0.42)
    reflected = signal.sosfilt(signal.butter(1, cutoff, fs=sr, output="sos"), audio, axis=0)
    result = audio.copy()
    for seconds, gain in ((0.011, 0.050), (0.023, 0.027), (0.037, -0.016), (0.058, 0.009)):
        offset = max(1, round(sr * seconds))
        if offset < len(audio):
            result[offset:] += gain * reflected[:-offset]
    return result


def process_cue(
    audio: np.ndarray,
    sr: int,
    reference: np.ndarray | None,
    reference_sr: int,
    options: Mapping,
) -> np.ndarray:
    """Apply enabled processors at the take's sample rate and preserve its length."""
    if not audio.size or not (
        options.get("eq_matching")
        or options.get("binaural_mode") in ("off", "static", "dynamic_hrtf")
        or options.get("reverb_match")
        or options.get("loudness_match") == "per_cue"
    ):
        return audio
    context = CueContext(
        None if reference is None else np.nan_to_num(reference, nan=0.0, posinf=0.0, neginf=0.0),
        reference_sr,
        options,
    )
    processed = audio.astype(np.float64, copy=False)
    for processor in (match_eq, match_binaural, match_reverb, match_loudness):
        processed = processor(processed, sr, context)
    peak = float(np.max(np.abs(processed)))
    if peak > 1 and options.get("binaural_mode") != "off":
        processed = processed / peak
    return processed.astype(audio.dtype, copy=False)


def stretch_wsola(audio: np.ndarray, sr: int, tempo: float) -> np.ndarray:
    """Accelerate audio by the same tempo ratio used by FFmpeg atempo."""
    if not math.isfinite(tempo) or tempo < 1:
        raise ValueError("tempo must be finite and at least 1")
    if tempo == 1 or not audio.size:
        return audio
    from pytsmod import wsola

    target = max(1, round(len(audio) / tempo))
    if target == 1:
        return audio[:1]
    window = min(len(audio) // 2, target, max(4, round(sr * 0.04)))
    if window < 4:
        return audio[:target]
    window -= window % 2
    channels_first = np.ascontiguousarray(audio.T)
    result = wsola(
        channels_first, target / len(audio), win_size=window,
        syn_hop_size=window // 2, tolerance=min(window // 2, round(sr * 0.015)),
    )
    result = result.T
    if audio.ndim == 2 and result.ndim == 1:
        result = result[:, None]
    if len(result) < target:
        padding = [(0, target - len(result))] + [(0, 0)] * (result.ndim - 1)
        result = np.pad(result, padding)
    return result[:target].astype(audio.dtype, copy=False)
