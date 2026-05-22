from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_qwen3_asr_recognizer_falls_back_to_full_duration_segment(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeTranscription:
        def __init__(self) -> None:
            self.language = "Japanese"
            self.text = "plain transcript"
            self.time_stamps = []

    class FakeQwenModel:
        def transcribe(self, **kwargs):
            captured["transcribe_kwargs"] = kwargs
            return [FakeTranscription()]

    class FakeQwenFactory:
        @staticmethod
        def from_pretrained(model_name, **kwargs):
            captured["model_name"] = model_name
            captured["model_kwargs"] = kwargs
            return FakeQwenModel()

    monkeypatch.setitem(sys.modules, "qwen_asr", SimpleNamespace(Qwen3ASRModel=FakeQwenFactory))

    from src.core.engines.asr.qwen3_asr import Qwen3AsrRecognizer

    recognizer = Qwen3AsrRecognizer(
        model_size="Qwen/Qwen3-ASR-0.6B",
        language="ja",
        device_map="cpu",
        dtype="float32",
        max_inference_batch_size=4,
        max_new_tokens=256,
    )
    monkeypatch.setattr(recognizer, "_read_duration_seconds", lambda _: 5.0)

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"not-a-real-wave")
    results = recognizer.recognize(str(audio_path))

    assert captured["model_name"] == "Qwen/Qwen3-ASR-0.6B"
    assert captured["model_kwargs"]["device_map"] == "cpu"
    assert captured["model_kwargs"]["max_inference_batch_size"] == 4
    assert captured["model_kwargs"]["max_new_tokens"] == 256
    assert captured["transcribe_kwargs"] == {
        "audio": str(audio_path),
        "context": "",
        "language": "Japanese",
        "return_time_stamps": False,
    }
    assert results == [{"start": 0.0, "end": 5.0, "text": "plain transcript"}]


def test_qwen3_asr_recognizer_normalizes_timestamp_items(tmp_path, monkeypatch):
    class FakeStamp:
        def __init__(self, text: str, start_time: int, end_time: int) -> None:
            self.text = text
            self.start_time = start_time
            self.end_time = end_time

    class FakeTranscription:
        def __init__(self) -> None:
            self.language = "English"
            self.text = "hello world"
            self.time_stamps = [
                FakeStamp("hello", 0, 900),
                FakeStamp("world", 900, 1800),
            ]

    class FakeQwenModel:
        def transcribe(self, **kwargs):
            return [FakeTranscription()]

    class FakeQwenFactory:
        @staticmethod
        def from_pretrained(model_name, **kwargs):
            return FakeQwenModel()

    monkeypatch.setitem(sys.modules, "qwen_asr", SimpleNamespace(Qwen3ASRModel=FakeQwenFactory))

    from src.core.engines.asr.qwen3_asr import Qwen3AsrRecognizer

    recognizer = Qwen3AsrRecognizer(
        model_size="Qwen/Qwen3-ASR-0.6B",
        language="en",
        device_map="cpu",
        return_time_stamps=True,
    )

    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"not-a-real-wave")
    results = recognizer.recognize(str(audio_path))

    assert results == [
        {"start": 0.0, "end": 0.9, "text": "hello"},
        {"start": 0.9, "end": 1.8, "text": "world"},
    ]


def test_execution_profile_builder_uses_qwen3_asr_default_model_when_settings_hold_whisper():
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
    profile = builder.build(category="asr", provider="qwen3_asr")

    assert profile["provider"] == "qwen3_asr"
    assert profile["model"] == "qwen3-asr-0.6b"


def test_asr_runtime_passes_qwen3_asr_provider_options_to_registry(tmp_path):
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
            "provider": "qwen3_asr",
            "model": "Qwen/Qwen3-ASR-0.6B",
            "common_options": {"language": "ja"},
            "provider_options": {
                "device_map": "cpu",
                "dtype": "float32",
                "max_inference_batch_size": 8,
                "return_time_stamps": True,
                "context": "anime dialogue",
            },
        },
    )

    registry.get.assert_called_once_with(
        "qwen3_asr",
        model_size="Qwen/Qwen3-ASR-0.6B",
        language="ja",
        device_map="cpu",
        dtype="float32",
        max_inference_batch_size=8,
        return_time_stamps=True,
        context="anime dialogue",
    )
