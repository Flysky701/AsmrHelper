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
        "beam_size": 3,
        "initial_prompt": "quiet speech",
        "no_speech_threshold": 0.8,
    }


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


def test_faster_whisper_runtime_reuses_model_when_vad_changes(tmp_path) -> None:
    from src.core.engines.asr.registry import AsrRegistry

    created_with: list[dict] = []
    vad_calls: list[bool] = []

    class Recognizer:
        def recognize(self, *_args, vad_filter=False, **_kwargs):
            vad_calls.append(vad_filter)
            return []

    def factory(**kwargs):
        created_with.append(kwargs)
        return Recognizer()

    registry = AsrRegistry()
    registry.register(
        "faster_whisper",
        factory=factory,
    )
    runtime = AsrEngineRuntime(registry=registry)
    input_path = tmp_path / "input.wav"
    input_path.write_bytes(b"fake")

    for vad_filter in (True, False):
        runtime.transcribe_file(
            input_path=str(input_path),
            output_path=None,
            profile={
                "provider": "faster_whisper",
                "model": "base",
                "common_options": {"language": "en"},
                "provider_options": {"vad_filter": vad_filter},
            },
        )

    assert len(created_with) == 1
    assert "vad_filter" not in created_with[0]
    assert vad_calls == [True, False]


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










def test_capability_validation_rejects_invalid_calibrated_options() -> None:
    service = CapabilityDescriptorService()

    with pytest.raises(AppValidationError, match="beam_size must be >= 1"):
        service.validate_options(
            category="asr",
            provider="faster_whisper",
            common_options={"language": "ja"},
            provider_options={"beam_size": 0},
        )

    with pytest.raises(AppValidationError, match="speed must be <= 2"):
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


def test_readiness_rejects_invalid_edge_speed_before_runtime(tmp_path, monkeypatch) -> None:
    from test_app_services import _saved_speech_recipe
    speech, recipe = _saved_speech_recipe(tmp_path, monkeypatch)
    # Simulate a persisted invalid recipe; readiness must recompile rather than
    # trusting an old validation result or falling back to legacy Edge options.
    invalid = speech.store.update("recipes", recipe["id"], {"provider_options": {"schema_version": 1, "speed": 2.1}})
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
                    "provider": "speech",
                    "model": None,
                    "options": {"speech_recipe_id": invalid["id"]},
                    "provider_options": {},
                }
            }
        },
    )

    assert result["ready"] is False
    assert result["issues"][0]["code"] == "SPEECH_RECIPE_NOT_READY"
    assert "speed" in result["issues"][0]["message"]
