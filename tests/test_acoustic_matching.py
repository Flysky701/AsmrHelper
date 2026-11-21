import numpy as np
import pytest
from scipy import signal

from src.core.asr.acoustic_profiler import active_rms_db
from src.mixer.acoustic_matching import process_cue, stretch_wsola


def test_default_passthrough_and_cue_loudness():
    sr = 48000
    take = (0.04 * np.sin(np.arange(sr) * 0.1)).astype(np.float32)
    reference = take * 2
    assert process_cue(take, sr, reference, sr, {}) is take
    result = process_cue(take, sr, reference, sr, {"loudness_match": "per_cue"})
    assert result.shape == take.shape and result.dtype == take.dtype
    assert active_rms_db(result, sr) == pytest.approx(active_rms_db(reference, sr), abs=0.1)


def test_dynamic_binaural_tracks_moving_source_and_delays_far_ear():
    sr = 48000
    take = np.random.default_rng(3).normal(0, 0.03, sr).astype(np.float32)
    reference = np.column_stack((take.copy(), take.copy()))
    reference[: sr // 2, 1] *= 0.1
    reference[sr // 2 :, 0] *= 0.1
    result = process_cue(take, sr, reference, sr, {"binaural_mode": "dynamic_hrtf"})
    left, right = result.T
    part = slice(sr // 10, sr // 4)
    assert np.std(left[part]) > 3 * np.std(right[part])
    lag = signal.correlation_lags(len(right[part]), len(left[part]))[
        signal.correlate(right[part], left[part]).argmax()
    ]
    assert 15 <= lag <= 29
    part = slice(sr * 3 // 4, sr * 9 // 10)
    assert np.std(right[part]) > 3 * np.std(left[part])


def test_eq_uses_reference_to_reduce_sibilance():
    sr = 44100
    take = np.random.default_rng(2).normal(0, 0.03, sr).astype(np.float32)
    reference = signal.sosfilt(signal.butter(4, 4000, fs=sr, output="sos"), take)
    result = process_cue(take, sr, reference, sr, {"eq_matching": True})
    freqs, before = signal.welch(take, fs=sr)
    _, after = signal.welch(result, fs=sr)
    band = (freqs >= 5000) & (freqs <= 8000)
    assert after[band].sum() < before[band].sum() * 0.6
    assert result.shape == take.shape


def test_reverb_adds_quiet_reflections():
    sr = 16000
    take = np.zeros(sr, dtype=np.float32)
    take[0] = 1
    result = process_cue(take, sr, None, sr, {"reverb_match": True})
    assert result[0] == 1
    assert 0.01 < np.max(np.abs(result[1:])) < 0.1
    assert result.shape == take.shape


def test_wsola_shortens_without_changing_dominant_pitch():
    pytest.importorskip("pytsmod")
    sr = 16000
    take = np.sin(np.arange(sr) / sr * (2 * np.pi * 250)).astype(np.float32)
    result = stretch_wsola(take[:, None], sr, 1.25)
    assert result.shape == (12800, 1)
    frequencies, power = signal.welch(result[:, 0], fs=sr, nperseg=4096)
    assert 245 <= frequencies[power.argmax()] <= 255
