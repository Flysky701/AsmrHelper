import numpy as np
import soundfile as sf

from src.mixer.room_tone import inpaint_room_tone, prepare_room_tone_bed


def test_room_tone_fills_a_long_cue_hole_and_preserves_background_event():
    sr = 16000
    rng = np.random.default_rng(23)
    source = rng.normal(0, 0.001, (3 * sr, 2)).astype(np.float32)
    source[sr : sr * 2] += 0.1
    background = source.copy()
    background[sr : sr * 2] = 0
    background[sr * 7 // 4 : sr * 2] = 0.05
    intervals = [{"start_time": 1.0, "end_time": 2.0}]
    repaired = inpaint_room_tone(background, sr, source, sr, intervals)
    np.testing.assert_array_equal(repaired[:sr], background[:sr])
    np.testing.assert_array_equal(repaired[sr * 7 // 4 :], background[sr * 7 // 4 :])
    np.testing.assert_array_equal(repaired[sr], background[sr])
    assert 0.0003 < np.std(repaired[sr * 5 // 4 : sr * 3 // 2]) < 0.002


def test_room_tone_skips_digital_silence():
    sr = 16000
    background = np.zeros(sr, dtype=np.float32)
    assert inpaint_room_tone(background, sr, background, sr, [{"start": 0.3, "end": 0.7}]) is background


def test_room_tone_bed_keeps_source_sample_rate(tmp_path):
    original = tmp_path / "original.wav"
    background = tmp_path / "background.wav"
    sr = 16000
    rng = np.random.default_rng(19)
    tone = rng.normal(0, 0.001, (sr * 2, 2))
    sf.write(original, tone, sr, subtype="FLOAT")
    sf.write(background, np.zeros(sr), sr // 2, subtype="FLOAT")
    output = prepare_room_tone_bed(
        background, original, [{"start": 0.4, "end": 1.3}], tmp_path
    )
    info = sf.info(output)
    assert info.samplerate == sr
    assert info.subtype == "FLOAT"
    assert sf.info(background).samplerate == sr // 2
