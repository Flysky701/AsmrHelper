from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from aiohttp import ClientConnectionError
import pytest

from src.app.errors import AppValidationError
from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.app.services.resource_service import ResourceService
from src.core.engines.asr.service import AsrEngineRuntime
from src.core.engines.tts.service import TtsEngineRuntime


def test_faster_whisper_descriptor_matches_supported_runtime_options() -> None:
    descriptor = CapabilityDescriptorService().get_descriptor("asr", "faster_whisper")
    options = {
        option["name"]: option
        for option in descriptor["provider_option_schema"]
    }

    assert set(options) == {
        "vad_filter",
        "beam_size",
        "initial_prompt",
        "no_speech_threshold",
    }
    assert options["vad_filter"]["default"] is False
    assert options["beam_size"]["default"] == 5
    assert options["beam_size"]["min"] == 1
    assert options["no_speech_threshold"]["default"] == 0.9
    assert options["no_speech_threshold"]["min"] == 0.0
    assert options["no_speech_threshold"]["max"] == 1.0


def test_faster_whisper_runtime_forwards_advertised_options() -> None:
    kwargs = AsrEngineRuntime._build_provider_kwargs(
        provider="faster_whisper",
        model="faster-whisper-base",
        common_options={"language": "auto"},
        provider_options={
            "vad_filter": True,
            "beam_size": 3,
            "initial_prompt": "quiet speech",
            "no_speech_threshold": 0.8,
        },
    )

    assert Path(kwargs.pop("model_size")).name == "base"
    assert kwargs == {
        "language": "auto",
        "vad_filter": True,
        "beam_size": 3,
        "initial_prompt": "quiet speech",
        "no_speech_threshold": 0.8,
    }


def test_faster_whisper_recognizer_passes_calibrated_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.asr as asr_module

    captured: dict = {}

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio_path, **kwargs):
            captured.update(kwargs)
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

    assert captured["language"] is None
    assert captured["vad_filter"] is True
    assert captured["vad_parameters"] == {
        "min_silence_duration_ms": 500,
        "speech_pad_ms": 200,
    }
    assert captured["beam_size"] == 3
    assert captured["initial_prompt"] == "quiet speech"
    assert captured["no_speech_threshold"] == 0.8


@pytest.mark.parametrize(
    ("speed", "expected_rate"),
    [
        (0.5, "-50%"),
        (1.0, "+0%"),
        (1.25, "+25%"),
        (2.0, "+100%"),
    ],
)
def test_edge_speed_is_mapped_to_upstream_rate(
    speed: float,
    expected_rate: str,
) -> None:
    kwargs = TtsEngineRuntime._build_engine_kwargs(
        "edge",
        {
            "common_options": {
                "voice": "zh-CN-XiaoxiaoNeural",
                "speed": speed,
            },
            "provider_options": {},
        },
    )

    assert kwargs == {
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": expected_rate,
    }


def test_edge_runtime_forwards_optional_proxy() -> None:
    kwargs = TtsEngineRuntime._build_engine_kwargs(
        "edge",
        {
            "common_options": {
                "voice": "zh-CN-XiaoxiaoNeural",
                "speed": 1.0,
            },
            "provider_options": {
                "proxy": "http://127.0.0.1:7890",
            },
        },
    )

    assert kwargs["proxy"] == "http://127.0.0.1:7890"


def test_qwen_runtime_forwards_target_language() -> None:
    kwargs = TtsEngineRuntime._build_engine_kwargs(
        "qwen3",
        {
            "common_options": {
                "voice": "Ono_Anna",
                "speed": 1.0,
                "language": "ja",
            },
            "provider_options": {"voice_profile_id": "C1"},
        },
    )

    assert kwargs["language"] == "ja"
    assert kwargs["voice_profile_id"] == "C1"


def test_voxcpm_runtime_prefers_managed_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.core.engines.tts.service as service_module

    monkeypatch.setattr(
        service_module,
        "resolve_model_reference",
        lambda model_id: r"E:\Projects\AsmrHelper\models\voxcpm2",
    )
    kwargs = TtsEngineRuntime._build_engine_kwargs(
        "voxcpm2",
        {
            "model": "voxcpm2",
            "common_options": {"voice": "default"},
            "provider_options": {},
        },
    )

    assert kwargs["model_dir"] == r"E:\Projects\AsmrHelper\models\voxcpm2"


def test_capability_validation_rejects_invalid_calibrated_options() -> None:
    service = CapabilityDescriptorService()

    with pytest.raises(AppValidationError, match="beam_size must be >= 1"):
        service.validate_options(
            category="asr",
            provider="faster_whisper",
            common_options={"language": "ja"},
            provider_options={"beam_size": 0},
        )

    with pytest.raises(AppValidationError, match="speed must be <= 2.0"):
        service.validate_options(
            category="tts",
            provider="edge",
            common_options={
                "voice": "zh-CN-XiaoxiaoNeural",
                "speed": 2.1,
            },
        )

    with pytest.raises(AppValidationError, match="unsupported options: rate"):
        service.validate_options(
            category="tts",
            provider="edge",
            common_options={
                "voice": "zh-CN-XiaoxiaoNeural",
                "speed": 1.0,
            },
            provider_options={"rate": "+10%"},
        )


@pytest.mark.asyncio
async def test_edge_network_request_retries_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts as tts_module

    calls: list[dict] = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            calls.append(kwargs)

        async def save(self, output_path):
            if len(calls) < 3:
                raise ClientConnectionError("temporary failure")
            Path(output_path).write_bytes(b"mp3")

    async def no_wait(delay):
        return None

    monkeypatch.setattr(tts_module.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(tts_module.asyncio, "sleep", no_wait)
    engine = tts_module.EdgeTTSEngine(proxy="http://127.0.0.1:7890")
    output_path = tmp_path / "probe.mp3"

    await engine._save_mp3_with_retry("test", output_path)

    assert len(calls) == 3
    assert calls[0]["proxy"] == "http://127.0.0.1:7890"
    assert output_path.read_bytes() == b"mp3"


@pytest.mark.asyncio
async def test_edge_synthesize_keeps_requested_mp3_without_in_place_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts as tts_module

    async def fake_save(text, output_path):
        Path(output_path).write_bytes(b"mp3")

    engine = tts_module.EdgeTTSEngine()
    monkeypatch.setattr(engine, "_save_mp3_with_retry", fake_save)
    monkeypatch.setattr(
        engine,
        "_convert_to_wav",
        lambda *_: pytest.fail("MP3 output must not be converted in place"),
    )
    output_path = tmp_path / "probe.mp3"

    written = await engine.synthesize_async("test", str(output_path))

    assert written == str(output_path)
    assert output_path.read_bytes() == b"mp3"


@pytest.mark.asyncio
async def test_edge_synthesize_rejects_unsupported_output_extension(tmp_path) -> None:
    import src.core.tts as tts_module

    engine = tts_module.EdgeTTSEngine()

    with pytest.raises(ValueError, match="must use .wav or .mp3"):
        await engine.synthesize_async("test", str(tmp_path / "probe.flac"))


@pytest.mark.asyncio
async def test_edge_batch_synthesis_limits_websocket_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import src.core.tts as tts_module

    active = 0
    peak = 0

    async def fake_synthesize(text, output_path):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return output_path

    engine = tts_module.EdgeTTSEngine()
    monkeypatch.setattr(engine, "synthesize_async", fake_synthesize)
    sentences = [f"sentence {index}" for index in range(12)]
    outputs = [tmp_path / f"{index}.wav" for index in range(12)]

    await engine._synthesize_all_async(sentences, outputs)

    assert peak == engine.MAX_CONCURRENT_REQUESTS


def test_readiness_rejects_invalid_edge_speed_before_runtime(tmp_path) -> None:
    model_service = SimpleNamespace(list_models=lambda: [])
    service = ResourceService(
        project_root=tmp_path,
        descriptor_service=CapabilityDescriptorService(),
        model_service=model_service,
        module_checker=lambda module: True,
    )
    service.ensure_workspace()

    result = service.check_task_readiness(
        task_type="pipeline",
        execution_profile={
            "stages": {
                "tts": {
                    "enabled": True,
                    "provider": "edge",
                    "model": "default",
                    "options": {
                        "voice": "zh-CN-XiaoxiaoNeural",
                        "speed": 2.1,
                        "language": "zh",
                    },
                    "provider_options": {},
                }
            }
        },
    )

    assert result["ready"] is False
    assert result["issues"][0]["code"] == "OPTION_INVALID"
    assert "speed must be <= 2.0" in result["issues"][0]["message"]


def test_generic_tts_provider_is_adapted_to_pipeline_segments(tmp_path) -> None:
    import numpy as np
    import soundfile as sf

    class TextOnlyEngine:
        def synthesize(self, text, output_path):
            sf.write(output_path, np.full(800, 0.25, dtype="float32"), 8000)
            return output_path

    class Registry:
        def get(self, name, **kwargs):
            assert name == "text_only"
            return TextOnlyEngine()

    output_path = tmp_path / "tts.wav"
    runtime = TtsEngineRuntime(registry=Registry())
    runtime.synthesize_segments(
        segments=[
            {"text": "first", "start_time": 0.0, "end_time": 0.1},
            {"text": "second", "start_time": 0.2, "end_time": 0.3},
        ],
        output_dir=str(tmp_path),
        output_path=str(output_path),
        profile={
            "provider": "text_only",
            "model": "text-only",
            "common_options": {"voice": "default", "speed": 1.0},
            "provider_options": {},
        },
        reference_duration=0.5,
        sample_rate=16000,
    )

    info = sf.info(str(output_path))
    assert info.samplerate == 16000
    assert info.frames == 8000
