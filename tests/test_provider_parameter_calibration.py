from __future__ import annotations

from types import SimpleNamespace

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

    assert kwargs == {
        "model_size": "base",
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
