from base64 import b64encode
from io import BytesIO
import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.engines.tts.openai_compatible import OpenAICompatibleTtsEngine
from src.core.engines.tts.service import TtsEngineRuntime


def wav_bytes():
    buffer = BytesIO()
    sf.write(buffer, np.ones(1600, dtype="float32") * 0.1, 16000, format="WAV")
    return buffer.getvalue()


def mock_transport(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            **kwargs,
            transport=httpx.MockTransport(handler),
        ),
    )


@pytest.mark.parametrize("api_format", ["speech", "mimo_chat"])
def test_remote_tts_payload_and_timeline(monkeypatch, tmp_path, api_format):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        assert str(request.url) == "https://speech.invalid/v1/" + (
            "audio/speech" if api_format == "speech" else "chat/completions"
        )
        if api_format == "speech":
            return httpx.Response(200, content=wav_bytes())
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"audio": {"data": b64encode(wav_bytes()).decode()}}}],
            },
        )

    mock_transport(monkeypatch, handler)
    engine = OpenAICompatibleTtsEngine(
        base_url="https://speech.invalid/v1/",
        api_key="test-key",
        model="custom-tts",
        voice="custom-voice",
        api_format=api_format,
        instructions="轻声朗读",
    )
    output = tmp_path / "timeline.wav"
    TtsEngineRuntime._synthesize_generic_segments(
        engine=engine,
        segments=[{"text": "你好", "start_time": 0.25}],
        output_dir=str(tmp_path),
        output_path=str(output),
        reference_duration=1,
        sample_rate=24000,
    )
    audio, rate = sf.read(output)
    assert rate == 24000 and len(audio) == 24000
    assert np.max(np.abs(audio[:6000])) == 0
    assert np.max(np.abs(audio[6000:8400])) > 0
    payload = requests[0]
    assert payload["model"] == "custom-tts"
    if api_format == "speech":
        assert payload["input"] == "你好"
        assert payload["instructions"] == "轻声朗读"
        assert payload["response_format"] == "wav"
    else:
        assert payload["messages"] == [
            {"role": "user", "content": "轻声朗读"},
            {"role": "assistant", "content": "你好"},
        ]
        assert payload["audio"] == {"voice": "custom-voice", "format": "wav"}


@pytest.mark.parametrize("status,content", [(401, b"test-key"), (200, b"not audio")])
def test_remote_errors_do_not_create_artifact_or_leak_key(monkeypatch, tmp_path, status, content):
    mock_transport(monkeypatch, lambda request: httpx.Response(status, content=content))
    engine = OpenAICompatibleTtsEngine(
        base_url="https://speech.invalid/v1",
        api_key="test-key",
        model="model",
        voice="voice",
    )
    output = tmp_path / "failed.wav"
    with pytest.raises(RuntimeError) as error:
        engine.synthesize("test", str(output))
    assert "test-key" not in str(error.value)
    assert not output.exists()


def test_custom_cloud_models_pass_readiness(monkeypatch, tmp_path):
    from src.app.services.resource_service import ResourceService
    from test_app_services import _saved_speech_recipe
    speech, recipe = _saved_speech_recipe(tmp_path, monkeypatch, provider="openai_compatible", model="custom-tts")
    service = ResourceService(
        project_root=tmp_path, model_service=SimpleNamespace(list_models=lambda: [])
    )
    profile = {
        "stages": {
            "translate": {"provider": "openai", "model": "custom-llm"},
            "tts": {"provider": "speech", "options": {"speech_recipe_id": recipe["id"]}},
            "mix": {"enabled": False},
            "export": {"enabled": False},
        }
    }
    assert service._check_pipeline_profile(profile) == []
    connection = speech.store.get("connections", recipe["connection_ref"])
    speech._credential_path(connection).unlink()
    issues = service._check_pipeline_profile(profile)
    assert any(item["code"] == "SPEECH_RECIPE_NOT_READY" and "凭据" in item["message"] for item in issues)


def test_external_tts_settings_keep_secrets_write_only():
    from test_app_services import _FakeConfig
    from src.app.services.settings_service import SettingsService

    config = _FakeConfig()
    service = SettingsService(config_manager=config)
    result = service.update_settings(
        {
            "external_tts": {
                "credential": "tts-secret",
                "base_url": "https://speech.invalid/v1",
                "model": "custom",
                "voice": "voice",
                "api_format": "mimo_chat",
            }
        }
    )
    assert result["external_tts"]["credential_configured"]
    assert "tts-secret" not in repr(result)
    service.update_settings({"external_tts": {"credential": "", "voice": "another"}})
    assert config.data["external_tts"]["api_key"] == "tts-secret"
    assert config.data["api"]["deepseek_api_key"] == "secret-deepseek"


def test_runtime_forwards_remote_model_and_voice():
    assert TtsEngineRuntime._build_engine_kwargs(
        "openai_compatible",
        {
            "model": "custom",
            "common_options": {"voice": "speaker", "speed": 1.2},
        },
    ) == {"model": "custom", "voice": "speaker", "speed": 1.2}


@pytest.mark.parametrize("speed", [0.5, 1.0, 1.2, 2.0])
def test_fish_saved_config_reaches_documented_protocol(monkeypatch, tmp_path, speed):
    from src.core.config import config
    from src.core.engines.tts.registry import TtsRegistry

    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.fish.audio/v1/tts"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["model"] == "s2-pro"
        expected = {"text": "你好", "reference_id": "saved-voice-id", "format": "wav"}
        if speed != 1.0:
            expected["prosody"] = {"speed": speed}
        assert json.loads(request.content) == expected
        return httpx.Response(200, content=wav_bytes())

    mock_transport(monkeypatch, handler)
    monkeypatch.setitem(config._config, "external_tts", {
        "base_url": "https://api.fish.audio/v1/", "api_key": "test-key",
        "api_format": "fish", "model": "s2-pro", "voice": "saved-voice-id",
        "instructions": "",
    })
    registry = TtsRegistry()
    registry._register_builtins()
    engine = registry.get("openai_compatible", **TtsEngineRuntime._build_engine_kwargs(
        "openai_compatible", {"common_options": {"speed": speed}}
    ))
    output = tmp_path / "fish-timeline.wav"
    TtsEngineRuntime._synthesize_generic_segments(
        engine=engine, segments=[{"text": "你好", "start_time": 0.25}],
        output_dir=str(tmp_path), output_path=str(output),
        reference_duration=1, sample_rate=24000,
    )
    assert len(requests) == 1
    audio, rate = sf.read(output)
    assert rate == 24000 and len(audio) == 24000
    assert np.max(np.abs(audio[:6000])) == 0
    assert np.max(np.abs(audio[6000:8400])) > 0


@pytest.mark.parametrize("options", [
    {"instructions": "轻声"}, {"speed": 0.4}, {"speed": 2.1},
])
def test_fish_rejects_unsupported_parameters_before_request(monkeypatch, tmp_path, options):
    def handler(request):
        pytest.fail("invalid configuration must not issue a billable request")

    mock_transport(monkeypatch, handler)
    engine = OpenAICompatibleTtsEngine(
        base_url="https://api.fish.audio/v1", api_key="test-key", api_format="fish",
        model="s2-pro", voice="voice-id", **options,
    )
    with pytest.raises(ValueError, match="Fish Audio"):
        engine.synthesize("你好", str(tmp_path / "invalid.wav"))


@pytest.mark.parametrize("status,body", [
    (401, b'{"error":"test-key"}'), (200, b'{"error":"test-key"}'),
])
def test_fish_errors_do_not_leak_credentials_or_create_output(monkeypatch, tmp_path, status, body):
    mock_transport(monkeypatch, lambda request: httpx.Response(status, content=body))
    engine = OpenAICompatibleTtsEngine(
        base_url="https://api.fish.audio/v1", api_key="test-key", api_format="fish",
        model="s2-pro", voice="voice-id",
    )
    output = tmp_path / "invalid.wav"
    with pytest.raises(RuntimeError) as error:
        engine.synthesize("你好", str(output))
    assert "test-key" not in str(error.value)
    assert not output.exists()
