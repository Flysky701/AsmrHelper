import numpy as np
import soundfile as sf

from src.core.asr.acoustic_profiler import profile_cues


def test_profiles_voiced_soft_and_breathy_cues(tmp_path):
    sr = 16000
    phase = np.arange(sr) / sr
    voice = np.sin(2 * np.pi * 180 * phase)
    noise = np.random.default_rng(41).standard_normal(sr)
    vocals = np.concatenate((0.2 * voice, 0.015 * voice, 0.02 * noise, np.zeros(sr)))
    path = tmp_path / "vocals.wav"
    sf.write(path, np.column_stack((vocals, -vocals)), sr, subtype="FLOAT")
    profiles = profile_cues(path, [{"start": i, "end": i + 1} for i in range(4)])
    assert [profile["delivery"] for profile in profiles] == ["normal", "soft", "whisper", "normal"]
    assert profiles[0]["voicing"] > profiles[2]["voicing"]
    assert profiles[0]["source_rms_percentile"] > profiles[1]["source_rms_percentile"]
    assert profiles[2]["high_frequency_ratio"] > 0.5
    assert profiles[3]["source_rms_db"] is None
