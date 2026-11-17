"""No model weights or real ASR inference: only provider wiring and conversion."""

from __future__ import annotations

import sys
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.core.engines.asr.anime_whisper import AnimeWhisperRecognizer


@pytest.fixture
def fake_transformers(monkeypatch):
    pipe = MagicMock(
        return_value={
            "text": "こんにちは。次です！",
            "chunks": [
                {"timestamp": (0.1, 0.6), "text": " こんにちは。"},
                {"timestamp": (0.7, 1.02), "text": "次です！"},
            ],
        }
    )
    factory = MagicMock(return_value=pipe)
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False, empty_cache=MagicMock()),
        float16="fp16",
        float32="fp32",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=factory))
    return factory, pipe, torch


def _builder():
    from src.app.services.capability_descriptor_service import CapabilityDescriptorService
    from src.app.services.execution_profile_builder import ExecutionProfileBuilder

    settings = MagicMock()
    settings.get_settings.return_value = {"processing": {"asr_model": "faster-whisper-base"}}
    return ExecutionProfileBuilder(settings, CapabilityDescriptorService())


def test_anime_whisper_service_decodes_audio_and_exports_real_srt(tmp_path, fake_transformers):
    from src.app.services.asr_engine_service import AsrEngineService
    from src.core.engines.asr.registry import AsrRegistry
    from src.core.engines.asr.service import AsrEngineRuntime
    from src.core.resources.model_reference import resolve_model_reference

    audio_path = tmp_path / "input.wav"
    # A synthetic stereo 8 kHz WAV exercises the bundled FFmpeg resampler.
    with wave.open(str(audio_path), "wb") as handle:
        handle.setparams((2, 2, 8000, 0, "NONE", "not compressed"))
        handle.writeframes(bytes(8000 * 2 * 2))
    registry = AsrRegistry()
    registry._register_builtins()
    service = AsrEngineService(
        profile_builder=_builder(), runtime=AsrEngineRuntime(registry=registry)
    )
    output = tmp_path / "subtitles" / "out.srt"

    result = service.transcribe_file(
        input_path=str(audio_path),
        output_path=str(output),
        provider="anime_whisper",
        provider_options={"no_repeat_ngram_size": 5, "repetition_penalty": 1.1},
    )

    factory, pipe, _ = fake_transformers
    factory.assert_called_once_with(
        "automatic-speech-recognition",
        model=resolve_model_reference("anime-whisper"),
        device="cpu",
        dtype="fp32",
        batch_size=1,
        trust_remote_code=False,
    )
    args, kwargs = pipe.call_args
    assert args[0]["sampling_rate"] == 16000
    assert args[0]["raw"].shape == (16000,)
    assert args[0]["raw"].dtype == np.float32
    assert kwargs == {
        "return_timestamps": True,
        "generate_kwargs": {
            "language": "ja",
            "task": "transcribe",
            "condition_on_prev_tokens": False,
            "no_repeat_ngram_size": 5,
            "repetition_penalty": 1.1,
        },
    }
    assert [(s.start, s.end, s.text) for s in result.segments] == [
        (0.1, 0.6, "こんにちは。"),
        (0.7, 1.0, "次です！"),
    ]
    assert result.segments[0].confidence is None
    assert result.segments[0].recognition_metadata == {
        "provider": "anime_whisper",
        "timestamp_source": "whisper_segment",
    }
    assert "00:00:00,100 --> 00:00:00,600\nこんにちは。" in output.read_text(encoding="utf-8")
    assert registry.is_loaded("anime_whisper")
    registry.unload("anime_whisper")
    assert not registry.is_loaded("anime_whisper")


@pytest.mark.parametrize("timestamp", [None, (None, 1), (float("nan"), 1), (1, 0), (2, 3)])
def test_anime_whisper_refuses_missing_or_invalid_timestamps(
    timestamp,
    tmp_path,
    fake_transformers,
    monkeypatch,
):
    _, pipe, _ = fake_transformers
    pipe.return_value = {"text": "hello", "chunks": [{"text": "hello", "timestamp": timestamp}]}
    recognizer = AnimeWhisperRecognizer(model_size="unused")
    monkeypatch.setattr(recognizer, "_read_audio", lambda _: np.zeros(16000, dtype=np.float32))
    output = tmp_path / "out.srt"
    with pytest.raises(RuntimeError, match="valid segment timestamps"):
        recognizer.recognize("unused.wav", str(output))
    assert not output.exists()


def test_anime_whisper_text_without_chunks_is_not_whole_audio_subtitle():
    with pytest.raises(RuntimeError, match="text without segment timestamps"):
        AnimeWhisperRecognizer._normalize_segments({"text": "hello"}, duration_seconds=10)
    assert (
        AnimeWhisperRecognizer._normalize_segments({"text": "", "chunks": []}, duration_seconds=10)
        == []
    )


def test_anime_whisper_open_final_cue_retains_native_start_and_marks_audio_boundary():
    result = AnimeWhisperRecognizer._normalize_segments(
        {
            "text": "first last",
            "chunks": [
                {"text": "first", "timestamp": (0.2, 0.7)},
                {"text": "last", "timestamp": (0.88, None)},
            ],
        },
        duration_seconds=3.111,
    )
    assert result[-1] == {
        "start": 0.88,
        "end": 3.111,
        "text": "last",
        "timestamp_source": "whisper_segment_audio_end",
    }
    assert result[0]["timestamp_source"] == "whisper_segment"
    with pytest.raises(RuntimeError, match="valid segment timestamps"):
        AnimeWhisperRecognizer._normalize_segments(
            {
                "chunks": [
                    {"text": "missing middle end", "timestamp": (0, None)},
                    {"text": "last", "timestamp": (1, 2)},
                ]
            },
            duration_seconds=3,
        )


@pytest.mark.parametrize(
    "options",
    [
        {"initial_prompt": "do not pass"},
        {"batch_size": "1"},
        {"batch_size": 0},
        {"batch_size": 17},
        {"no_repeat_ngram_size": -1},
        {"repetition_penalty": 0.5},
    ],
)
def test_anime_whisper_rejects_unwired_or_invalid_options(options):
    from src.app.errors import AppValidationError

    with pytest.raises(AppValidationError):
        _builder().build(category="asr", provider="anime_whisper", provider_options=options)


def test_anime_whisper_is_opt_in_and_japanese_only():
    from src.app.errors import AppValidationError

    builder = _builder()
    assert builder.build(category="asr")["provider"] == "faster_whisper"
    profile = builder.build(category="asr", model="anime-whisper")
    assert profile["provider"] == "anime_whisper"
    assert profile["model"] == "anime-whisper"
    with pytest.raises(AppValidationError):
        builder.build(category="asr", provider="anime_whisper", common_options={"language": "en"})


def test_anime_whisper_resource_mapping_local_path_and_isolated_readiness(tmp_path, monkeypatch):
    from src.core.engines.asr.service import _resolve_model_name
    from src.core.resources.model_catalog import ModelCatalog, ModelEntry
    from src.core.resources.model_status import ModelStatusResolver
    from src.core.runtime.profiles import RuntimeProfileResolver
    from src.core.runtime.router import RuntimeRouter

    entry = ModelCatalog().get("anime-whisper")
    install_dir = tmp_path / "weights"
    monkeypatch.setattr(ModelEntry, "resolved_install_dir", lambda _: install_dir)
    assert _resolve_model_name("anime_whisper", entry.id) == "litagin/anime-whisper"
    assert entry.required_python_extras == ["anime_whisper"]
    assert entry.install_strategy == "huggingface_snapshot"
    install_dir.mkdir()
    for name in entry.required_files:
        (install_dir / name).write_bytes(b"mock asset, not model weights")
    assert _resolve_model_name("anime_whisper", entry.id) == str(install_dir)

    runtime_resolver = RuntimeProfileResolver(project_root=tmp_path)
    runtime = runtime_resolver.resolve(entry.runtime_profile)
    assert runtime.isolated and runtime.project_extra == "anime_whisper"
    assert RuntimeRouter(resolver=runtime_resolver).asr_profile("anime_whisper") == runtime.id
    status_resolver = ModelStatusResolver(runtime_resolver=runtime_resolver)
    status = status_resolver.resolve(entry)
    assert status.weights_ready and not status.executable
    assert any(issue.code == "RUNTIME_ENVIRONMENT_MISSING" for issue in status.issues)
    # With an interpreter present, readiness checks the selected runtime imports.
    runtime.python_executable.parent.mkdir(parents=True)
    runtime.python_executable.touch()
    monkeypatch.setattr(
        runtime_resolver, "check_modules", lambda _, names: "transformers" not in names
    )
    status = status_resolver.resolve(entry)
    assert any(issue.requirement == "transformers" for issue in status.issues)
    (install_dir / "model.safetensors").unlink()
    assert not status_resolver.resolve(entry).weights_ready


def test_anime_whisper_reports_missing_optional_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(RuntimeError, match="optional Transformers runtime"):
        AnimeWhisperRecognizer(model_size="unused")
