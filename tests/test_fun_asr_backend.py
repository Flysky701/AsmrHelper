from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_fun_asr_recognizer_normalizes_sentence_info(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeModel:
        def generate(self, **kwargs):
            captured["generate_kwargs"] = kwargs
            return [
                {
                    "text": "hello world",
                    "sentence_info": [
                        {"start": 0, "end": 1200, "text": "hello"},
                        {"start": 1200, "end": 2400, "text": "world"},
                    ],
                }
            ]

    def fake_auto_model(**kwargs):
        captured["model_kwargs"] = kwargs
        return FakeModel()

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=fake_auto_model))

    from src.core.engines.asr.fun_asr import FunAsrRecognizer

    recognizer = FunAsrRecognizer(
        model_size="FunAudioLLM/Fun-ASR-Nano-2512",
        language="ja",
        device="cpu",
        sentence_timestamp=True,
    )
    monkeypatch.setattr(recognizer, "_read_duration_seconds", lambda _: 2.4)

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"not-a-real-wave")
    output_path = tmp_path / "out.txt"
    results = recognizer.recognize(str(audio_path), str(output_path))

    assert captured["model_kwargs"] == {
        "model": "FunAudioLLM/Fun-ASR-Nano-2512",
        "device": "cpu",
        "hub": "hf",
        "trust_remote_code": True,
    }
    assert captured["generate_kwargs"]["language"] == "Japanese"
    assert results == [
        {"start": 0.0, "end": 1.2, "text": "hello"},
        {"start": 1.2, "end": 2.4, "text": "world"},
    ]
    assert output_path.exists()


def test_fun_asr_recognizer_falls_back_to_full_duration_segment(tmp_path, monkeypatch):
    class FakeModel:
        def generate(self, **kwargs):
            return [{"text": "plain transcript"}]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=lambda **_: FakeModel()))

    from src.core.engines.asr.fun_asr import FunAsrRecognizer

    recognizer = FunAsrRecognizer(
        model_size="FunAudioLLM/Fun-ASR-Nano-2512",
        language="auto",
        device="cpu",
    )
    monkeypatch.setattr(recognizer, "_read_duration_seconds", lambda _: 5.0)

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"not-a-real-wave")
    results = recognizer.recognize(str(audio_path))

    assert results == [{"start": 0.0, "end": 5.0, "text": "plain transcript"}]


def test_execution_profile_builder_uses_fun_asr_default_model_when_settings_hold_whisper():
    from src.app.services.capability_descriptor_service import CapabilityDescriptorService
    from src.app.services.execution_profile_builder import ExecutionProfileBuilder

    settings = MagicMock()
    settings.get_effective_settings.return_value = {
        "processing": {"asr_model": "large-v3", "vocal_model": "htdemucs"},
        "tts": {"engine": "edge"},
        "api": {"provider": "deepseek"},
    }

    builder = ExecutionProfileBuilder(
        settings_service=settings,
        descriptor_service=CapabilityDescriptorService(),
    )
    profile = builder.build(category="asr", provider="fun_asr")

    assert profile["provider"] == "fun_asr"
    assert profile["model"] == "fun-asr-nano-2512"


def test_asr_runtime_passes_fun_asr_provider_options_to_registry(tmp_path):
    from src.core.engines.asr.service import AsrEngineRuntime

    registry = MagicMock()
    recognizer = MagicMock()
    recognizer.recognize.return_value = [{"start": 0.0, "end": 1.0, "text": "ok"}]
    registry.get.return_value = recognizer
    runtime = AsrEngineRuntime(registry=registry)

    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake")

    runtime.transcribe_file(
        input_path=str(audio_path),
        output_path=None,
        profile={
            "provider": "fun_asr",
            "model": "FunAudioLLM/Fun-ASR-Nano-2512",
            "common_options": {"language": "ja"},
            "provider_options": {
                "hub": "hf",
                "device": "cpu",
                "sentence_timestamp": True,
                "remote_code_path": "C:/models/Fun-ASR/model.py",
            },
        },
    )

    registry.get.assert_called_once_with(
        "fun_asr",
        model_size="FunAudioLLM/Fun-ASR-Nano-2512",
        language="ja",
        hub="hf",
        device="cpu",
        sentence_timestamp=True,
        remote_code_path="C:/models/Fun-ASR/model.py",
    )
