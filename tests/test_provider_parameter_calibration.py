from __future__ import annotations

from types import SimpleNamespace

import pytest



def test_faster_whisper_recognizer_passes_calibrated_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.asr as asr_module

    captured: list[dict] = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, **kwargs):
            captured.append(kwargs)
            return iter(()), SimpleNamespace(duration=0.0)

    monkeypatch.setattr(asr_module, "WhisperModel", FakeWhisperModel)
    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"fake")

    recognizer = asr_module.ASRRecognizer(
        model_size="base",
        device="cpu",
        language="auto",
        vad_filter=True,
        beam_size=3,
        initial_prompt="quiet speech",
        no_speech_threshold=0.8,
    )
    recognizer.recognize(str(input_path), show_progress=False)
    recognizer.recognize(str(input_path), show_progress=False, vad_filter=False)

    assert captured[0]["language"] is None
    assert captured[0]["vad_filter"] is True
    assert captured[0]["vad_parameters"] == {
        "min_silence_duration_ms": 500,
        "speech_pad_ms": 200,
    }
    assert captured[0]["beam_size"] == 3
    assert captured[0]["initial_prompt"] == "quiet speech"
    assert captured[0]["no_speech_threshold"] == 0.8
    assert captured[1]["vad_filter"] is False
    assert captured[1]["vad_parameters"] is None


def test_faster_whisper_separates_speech_filter_score_from_explicit_confidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.asr as asr_module
    import math
    from src.core.engines.asr.service import _entry_confidence

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, _audio_path, **_kwargs):
            segment = SimpleNamespace(
                start=0.0,
                end=1.0,
                text="quiet",
                words=[],
                no_speech_prob=0.9,
                avg_logprob=-0.42,
            )
            return iter((segment,)), SimpleNamespace(duration=1.0)

    monkeypatch.setattr(asr_module, "WhisperModel", FakeWhisperModel)
    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"fake")
    recognizer = asr_module.ASRRecognizer(model_size="base", device="cpu")
    recognizer.postprocessor = SimpleNamespace(process=lambda entries: entries)

    entries = recognizer.recognize(str(input_path), show_progress=False)

    # Speech presence can guide the legacy filter; it is not transcript accuracy.
    assert entries[0]["log_prob"] == pytest.approx(math.log(0.1 / 0.9))
    assert _entry_confidence(entries[0]) is None
    preserved = recognizer.recognize(str(input_path), show_progress=False, preserve_segments=True)
    assert _entry_confidence(preserved[0]) == -0.42
    assert preserved[0]["recognition_metadata"]["confidence_kind"] == "avg_logprob"
