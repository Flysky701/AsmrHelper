from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_voice_analysis_routes_catalog_model_id_through_asr_runtime(
    monkeypatch,
    tmp_path,
):
    from src.core.engines.asr import service as asr_service_module
    from src.core.tts.audio_preprocessor import AudioPreprocessor

    captured = {}

    class FakeRuntime:
        def transcribe_file(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(
                        start=0.0,
                        end=1.25,
                        text=" test ",
                        confidence=0.82,
                    )
                ]
            )

    monkeypatch.setattr(asr_service_module, "AsrEngineRuntime", FakeRuntime)
    monkeypatch.setattr(
        "src.config.config.get",
        lambda key, default=None: (
            "faster-whisper-base" if key == "processing.asr_model" else default
        ),
    )
    preprocessor = AudioPreprocessor(output_dir=str(tmp_path))

    result = preprocessor._run_asr(str(tmp_path / "input.wav"), language="ja")

    assert captured["profile"] == {
        "provider": "faster_whisper",
        "model": "faster-whisper-base",
        "common_options": {"language": "ja"},
        "provider_options": {"vad_filter": True, "preserve_segments": True},
    }
    assert result == [
        {
            "start": 0.0,
            "end": 1.25,
            "text": "test",
            "asr_confidence": 0.82,
            "recognition_metadata": {},
        }
    ]


def test_voice_analysis_retries_without_vad_only_after_empty_result(
    monkeypatch,
    tmp_path,
):
    from src.core.engines.asr import service as asr_service_module
    from src.core.tts.audio_preprocessor import AudioPreprocessor

    vad_calls = []

    class FakeRuntime:
        def transcribe_file(self, **kwargs):
            vad_filter = kwargs["profile"]["provider_options"]["vad_filter"]
            vad_calls.append(vad_filter)
            if vad_filter:
                return SimpleNamespace(segments=[])
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(
                        start=0.1,
                        end=1.2,
                        text="whisper",
                        confidence=0.61,
                    )
                ]
            )

    monkeypatch.setattr(asr_service_module, "AsrEngineRuntime", FakeRuntime)
    preprocessor = AudioPreprocessor(output_dir=str(tmp_path))

    result = preprocessor._run_asr(str(tmp_path / "input.wav"), language="en")

    assert vad_calls == [True, False]
    assert result[0]["text"] == "whisper"
    assert result[0]["asr_confidence"] == 0.61


def test_asr_runtime_does_not_use_legacy_speech_score_as_confidence(tmp_path):
    from src.core.engines.asr.service import AsrEngineRuntime

    class Registry:
        def get(self, *_args, **_kwargs):
            return SimpleNamespace(
                recognize=lambda *_args, **_kwargs: [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "hello",
                        "log_prob": 0.0,
                    }
                ]
            )

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    document = AsrEngineRuntime(registry=Registry()).transcribe_file(
        input_path=str(audio_path),
        output_path=None,
        profile={
            "provider": "faster_whisper",
            "model": "base",
            "common_options": {"language": "en"},
        },
    )

    assert document.segments[0].confidence is None


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf")])
def test_asr_runtime_normalizes_non_finite_explicit_confidence(
    confidence,
    tmp_path,
):
    from src.core.engines.asr.service import AsrEngineRuntime

    class Registry:
        def get(self, *_args, **_kwargs):
            return SimpleNamespace(
                recognize=lambda *_args, **_kwargs: [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "quiet",
                        "confidence": confidence,
                    }
                ]
            )

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"fake")
    document = AsrEngineRuntime(registry=Registry()).transcribe_file(
        input_path=str(audio_path),
        output_path=None,
        profile={
            "provider": "faster_whisper",
            "model": "base",
            "common_options": {"language": "en"},
        },
    )

    assert document.segments[0].confidence is None
