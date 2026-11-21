"""Small synthetic fixtures for N-track and same-source reference subtraction."""

import numpy as np
import pytest
import soundfile as sf

from src.mixer.difference import _estimate_delay, extract_difference
from src.mixer.multitrack import mix_tracks


def write(tmp_path, name, data, rate=8000):
    path = tmp_path / name
    sf.write(path, data, rate, subtype="FLOAT")
    return path


def read(path):
    return sf.read(path, always_2d=True, dtype="float64")[0]


def test_alignment_selects_channel_within_actual_twenty_second_analysis():
    # Direct low-rate DSP input covers 32 seconds using only 3,200 stereo samples.
    rate, count, expected_delay = 100, 3200, 7
    rng = np.random.default_rng(23)
    reference = np.zeros((count, 2), dtype=np.float32)
    reference[:, 1] = rng.normal(0, 0.05, count)
    reference[2300:, 0] = rng.normal(0, 0.9, count - 2300)
    mixed = np.zeros_like(reference)
    mixed[expected_delay:] = reference[:-expected_delay]
    # The left channel dominates the complete calibration window but is silent
    # throughout the actual analysis interval [1, 21), so alignment must use right.
    delay, correlation, boundary, seconds = _estimate_delay(
        mixed, reference, rate, rate, 31 * rate, 0.2, None)
    assert delay == expected_delay
    assert correlation == pytest.approx(1.0)
    assert not boundary
    assert seconds == 20


@pytest.mark.parametrize("delay", [4317, -2381])
def test_difference_recovers_stereo_effect_and_sample_offset(tmp_path, delay):
    rate, count = 48000, 96000
    rng = np.random.default_rng(41)
    reference = rng.normal(0, 0.1, (count, 2)).astype(np.float32)
    effect = np.zeros_like(reference)
    time = np.arange(12000) / rate
    effect[72000:84000] = (0.2 * np.sin(2 * np.pi * 880 * time))[:, None]
    mixed = effect.copy()
    start, end = max(0, delay), min(count, count + delay)
    mixed[start:end] += reference[start-delay:end-delay] * [0.8, 1.1]
    mix = write(tmp_path, "mixed.wav", mixed, rate)
    ref = write(tmp_path, "reference.wav", reference, rate)
    output = tmp_path / "difference.wav"
    meta = extract_difference(mix, ref, output, auto_align=True, auto_gain=True,
                              calibration_start=0.2, calibration_end=1.3, search_seconds=0.2)
    assert meta["offset_samples"] == delay
    assert meta["gains"] == pytest.approx([0.8, 1.1], abs=1e-7)
    assert abs(meta["correlation"]) > 0.9999
    assert meta["coverage_start"] == start / rate
    assert meta["coverage_end"] == end / rate
    np.testing.assert_allclose(read(output), effect, atol=1e-7)


def test_difference_preserves_uncovered_edges_and_float_peak(tmp_path):
    mixed = np.full(8000, 0.8)
    reference = np.full(4000, -0.7)
    mix = write(tmp_path, "mixed.wav", mixed)
    ref = write(tmp_path, "reference.wav", reference)
    output = tmp_path / "difference.wav"
    meta = extract_difference(mix, ref, output, offset_ms=125)
    expected = mixed.copy()
    expected[1000:5000] = 1.5
    np.testing.assert_allclose(read(output)[:, 0], expected, atol=1e-7)
    assert sf.info(output).subtype == "FLOAT"
    assert meta["peak"] == pytest.approx(1.5)
    assert meta["uncaptured_seconds"] == 0.5
    assert any("未覆盖" in text for text in meta["warnings"])
    assert any("削波" in text for text in meta["warnings"])


@pytest.mark.parametrize("mixed_rate,reference_rate", [(8000, 16000), (16000, 8000)])
def test_difference_resamples_and_duplicates_mono_without_level_change(
    tmp_path, mixed_rate, reference_rate,
):
    def tone(rate):
        return 0.2 * np.sin(2 * np.pi * 213 * np.arange(rate) / rate)
    mixed = np.column_stack([tone(mixed_rate) * 0.6, tone(mixed_rate) * 1.2])
    mix = write(tmp_path, "mixed.wav", mixed, mixed_rate)
    ref = write(tmp_path, "reference.wav", tone(reference_rate), reference_rate)
    output = tmp_path / "difference.wav"
    meta = extract_difference(mix, ref, output, gain_left=0.6, gain_right=1.2)
    assert meta["sample_rate"] == mixed_rate
    assert meta["channels"] == 2
    assert len(read(output)) == mixed_rate
    assert np.max(np.abs(read(output)[100:-100])) < 1e-4


def test_manual_delay_and_automatic_negative_gain(tmp_path):
    rng = np.random.default_rng(7)
    reference = rng.normal(0, 0.1, 8000)
    mixed = np.r_[np.zeros(80), reference[:-80] * -0.7]
    mix = write(tmp_path, "mixed.wav", mixed)
    ref = write(tmp_path, "reference.wav", reference)
    output = tmp_path / "difference.wav"
    meta = extract_difference(mix, ref, output, offset_ms=10, auto_gain=True,
                              calibration_start=0.1, calibration_end=0.8)
    assert meta["gains"] == pytest.approx([-0.7], abs=1e-7)
    assert np.max(np.abs(read(output))) < 1e-7


@pytest.mark.parametrize("length,expected_frames", [("longest", 7200), ("main", 3200)])
def test_multitrack_offsets_gains_muting_rate_and_channels(tmp_path, length, expected_frames):
    first = write(tmp_path, "first.wav", np.full(3200, 0.2))
    second = write(tmp_path, "second.wav", np.tile([0.1, 0.2], (4800, 1)), 16000)
    third = write(tmp_path, "third.wav", np.full(3200, 0.1))
    muted = write(tmp_path, "muted.wav", np.ones(6400))
    output = tmp_path / "mix.wav"
    meta = mix_tracks([
        {"path": first, "gain": 0.5},
        {"path": second, "gain": 2, "offset_ms": 200},
        {"path": third, "gain": 0.5, "offset_ms": -100},
        {"path": muted, "gain": 50, "offset_ms": 100, "muted": True},
    ], output, output_length=length)
    expected = np.zeros((expected_frames, 2))
    expected[:3200] += 0.1
    expected[1600:min(4000, expected_frames)] += [0.2, 0.4]
    expected[:2400] += 0.05
    np.testing.assert_allclose(read(output), expected, atol=1e-6)
    assert meta["sample_rate"] == 8000
    assert meta["channels"] == 2
    assert meta["track_count"] == 4
    assert meta["safety_gain"] == 1


def test_peak_safety_only_attenuates_and_keeps_relative_gains(tmp_path):
    source = write(tmp_path, "source.wav", np.tile([0.7, 0.35], (800, 1)))
    output = tmp_path / "mix.wav"
    meta = mix_tracks([{"path": source}, {"path": source, "gain": 2}], output)
    assert meta["peak_before"] == pytest.approx(2.1)
    assert meta["safety_gain"] == pytest.approx(0.98 / 2.1)
    np.testing.assert_allclose(read(output), np.tile([0.98, 0.49], (800, 1)), atol=1e-7)
    meta = mix_tracks([{"path": source, "gain": 0.1}], output)
    assert meta["safety_gain"] == 1
    np.testing.assert_allclose(read(output), np.tile([0.07, 0.035], (800, 1)), atol=1e-7)


def test_all_muted_and_fully_advanced_tracks(tmp_path):
    source = write(tmp_path, "source.wav", np.full(800, 0.2))
    output = tmp_path / "mix.wav"
    mix_tracks([{"path": source, "muted": True}], output)
    assert not read(output).any()
    mix_tracks([{"path": source, "offset_ms": -500}], output)
    assert read(output).shape == (1, 1)
    assert not read(output).any()
    mix_tracks([{"path": source, "offset_ms": 100}], output, output_length="main")
    assert len(read(output)) == 1600
    assert not read(output)[:800].any()


@pytest.mark.parametrize("options", [
    {"gain": -1}, {"gain": float("nan")}, {"offset_ms": float("inf")}, {"muted": "false"},
])
def test_invalid_track_options(tmp_path, options):
    source = write(tmp_path, "source.wav", np.full(800, 0.1))
    with pytest.raises(ValueError):
        mix_tracks([{"path": source, **options}], tmp_path / "mix.wav")


def test_invalid_audio_and_output_cannot_destroy_source(tmp_path):
    source = write(tmp_path, "source.wav", np.full(800, 0.1))
    original = source.read_bytes()
    with pytest.raises(ValueError, match="覆盖"):
        mix_tracks([{"path": source}], source)
    with pytest.raises(ValueError, match="覆盖"):
        extract_difference(source, source, source)
    assert source.read_bytes() == original
    surround = write(tmp_path, "surround.wav", np.zeros((800, 3)))
    invalid = write(tmp_path, "nan.wav", np.full(800, float("nan")))
    empty = write(tmp_path, "empty.wav", np.empty(0))
    for path in [surround, invalid, empty, tmp_path / "missing.wav"]:
        with pytest.raises(ValueError):
            mix_tracks([{"path": path}], tmp_path / "mix.wav")
    with pytest.raises(ValueError):
        mix_tracks([], tmp_path / "mix.wav")


def test_difference_rejects_silent_calibration_and_no_overlap(tmp_path):
    source = write(tmp_path, "source.wav", np.zeros(8000))
    output = tmp_path / "difference.wav"
    with pytest.raises(ValueError, match="接近静音"):
        extract_difference(source, source, output, auto_gain=True)
    with pytest.raises(ValueError, match="相关性太低"):
        extract_difference(source, source, output, auto_align=True)
    with pytest.raises(ValueError, match="没有重叠"):
        extract_difference(source, source, output, offset_ms=2000)
    with pytest.raises(ValueError, match="0.2"):
        extract_difference(source, source, output, auto_gain=True, calibration_end=0.1)
    with pytest.raises(ValueError, match="校准区间"):
        extract_difference(source, source, output, calibration_end=2)


@pytest.mark.parametrize("operation", ["mix", "difference"])
def test_cancellation_preserves_existing_output(tmp_path, operation):
    source = write(tmp_path, "source.wav", np.full(8000, 0.1))
    output = write(tmp_path, "output.wav", np.full(100, 0.5))
    previous = output.read_bytes()
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls >= 6:
            raise RuntimeError("cancel-test")

    with pytest.raises(RuntimeError, match="cancel-test"):
        if operation == "mix":
            mix_tracks([{"path": source}], output, check_cancel=cancel)
        else:
            extract_difference(source, source, output, check_cancel=cancel)
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".output-*.wav"))
