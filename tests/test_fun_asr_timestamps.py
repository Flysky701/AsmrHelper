from types import SimpleNamespace
import sys

import pytest

from src.core.engines.asr.fun_asr import FunAsrRecognizer


@pytest.mark.parametrize("start,end", [(0, 420), (420, 980), (420, 1000), (420, 5580)])
def test_vad_sentence_bounds_always_use_milliseconds(start, end):
    # Older Nano checkpoints lack CTC tensors. FunASR then supplies coarse
    # VAD sentence bounds, including values smaller than one second.
    result = FunAsrRecognizer._normalize_segments(
        [{"text": "一句话", "sentence_info": [
            {"start": start, "end": end, "text": "一句话", "timestamp": []}
        ]}],
        duration_seconds=5.616,
    )
    assert result == [{"start": start / 1000, "end": end / 1000, "text": "一句话"}]


def test_nano_token_seconds_do_not_change_units_after_1000_seconds():
    result = FunAsrRecognizer._normalize_segments(
        [{"text": "next", "timestamps": [
            {"token": "next", "start_time": 1001.2, "end_time": 1002.0}
        ]}],
        duration_seconds=1200,
    )
    assert result == [{"start": 1001.2, "end": 1002.0, "text": "next"}]


def test_legacy_timestamp_pairs_use_milliseconds_below_one_second():
    result = FunAsrRecognizer._normalize_segments(
        [{"text": "hello", "words": ["hello"], "timestamp": [[100, 900]]}],
        duration_seconds=1,
    )
    assert result == [{"start": 0.1, "end": 0.9, "text": "hello"}]


def test_recognize_bounds_are_clamped_to_actual_audio_duration(tmp_path, monkeypatch):
    model = SimpleNamespace(generate=lambda **_: [{"sentence_info": [
        {"text": "hello", "start": -100, "end": 2300}
    ]}])
    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=lambda **_: model))
    recognizer = FunAsrRecognizer(model_size="local", device="cpu")
    monkeypatch.setattr(recognizer, "_read_duration_seconds", lambda _: 2.0)
    assert recognizer.recognize(str(tmp_path / "audio.wav")) == [
        {"text": "hello", "start": 0.0, "end": 2.0}
    ]
