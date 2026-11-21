from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest


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

    assert results == [{"start": 0.0, "end": 5.0, "text": "plain transcript", "timestamp_source": "whole_audio"}]


def test_fun_asr_recognizer_uses_vad_timestamp_items_without_sentence_info(
    tmp_path, monkeypatch
):
    class FakeModel:
        def generate(self, **kwargs):
            return [
                {
                    "text": "こんにちは。次です！",
                    "sentence_info": [],
                    "timestamps": [
                        {"text": "こんにちは", "start_time": 1.0, "end_time": 2.0},
                        {"text": "。", "start_time": 2.0, "end_time": 2.1},
                        {"text": "次です", "start_time": 3.0, "end_time": 3.8},
                        {"text": "！", "start_time": 3.8, "end_time": 3.9},
                    ],
                }
            ]

    monkeypatch.setitem(sys.modules, "funasr", SimpleNamespace(AutoModel=lambda **_: FakeModel()))

    from src.core.engines.asr.fun_asr import FunAsrRecognizer

    recognizer = FunAsrRecognizer(model_size="FunAudioLLM/Fun-ASR-Nano-2512")
    audio_path = tmp_path / "input.wav"
    audio_path.write_bytes(b"not-a-real-wave")

    assert recognizer.recognize(str(audio_path)) == [
        {"start": 1.0, "end": 2.1, "text": "こんにちは。"},
        {"start": 3.0, "end": 3.9, "text": "次です！"},
    ]


def test_fun_asr_recognizer_reports_nested_runtime_dependency(monkeypatch):
    fake_module = ModuleType("funasr")

    def missing_auto_model(name: str):
        if name == "AutoModel":
            raise ModuleNotFoundError(
                "No module named 'torchaudio'",
                name="torchaudio",
            )
        raise AttributeError(name)

    fake_module.__getattr__ = missing_auto_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "funasr", fake_module)

    from src.core.engines.asr.fun_asr import FunAsrRecognizer

    with pytest.raises(RuntimeError, match="runtime dependency 'torchaudio' is missing"):
        FunAsrRecognizer(model_size="FunAudioLLM/Fun-ASR-Nano-2512")
