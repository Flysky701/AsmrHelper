"""Offline contract tests; fixtures are generated audio, never a live API call."""
import json

import httpx
import pytest

from src.core.speech.cloud_elevenlabs import ElevenLabsSpeechProvider
from src.core.speech.providers import ProviderError
from test_cloud_speech_transport import install_transport as mock_http, wav_bytes as wav


def recipe(**changes):
    value = {"provider_id": "elevenlabs", "model": "eleven_v3", "mode": "hosted",
        "connection_ref": "eleven-connection", "variant": {"kind": "hosted", "value": "fixtureVoice123"},
        "language": "zh", "provider_options": {"schema_version": 1}}
    value.update(changes)
    return value


def request(**changes):
    value = recipe(**changes)
    return {**value, "provider_version": "1", "text": "Test audio.",
        "parameters": ElevenLabsSpeechProvider().compile(value, {}, "Test audio.", {})}


def context(base="https://api.elevenlabs.io"):
    return {"connection": {"provider_id": "elevenlabs", "base_url": base, "api_key": "fixture-key"}}


@pytest.mark.parametrize("model,options,expected", [
    ("eleven_v3", {"schema_version": 1, "stability": 1}, {"stability": 1}),
    ("eleven_v4", {"schema_version": 1, "stability": .5, "similarity_boost": .7},
     {"stability": .5, "similarity_boost": .7}),
    ("eleven_flash_v2_5", {"schema_version": 1, "speed": 1.2, "stability": .3}, {"speed": 1.2, "stability": .3}),
])
def test_native_request_and_wav_metadata(monkeypatch, tmp_path, model, options, expected):
    def handler(req):
        assert str(req.url) == "https://api.elevenlabs.io/v1/text-to-speech/fixtureVoice123?output_format=wav_24000"
        assert req.headers["xi-api-key"] == "fixture-key"
        assert "authorization" not in req.headers
        assert json.loads(req.content) == {"text": "Test audio.", "model_id": model,
            "language_code": "zh", "voice_settings": expected}
        return httpx.Response(200, content=wav(), headers={"request-id": "mock-123"})
    mock_http(monkeypatch, handler)
    compiled = request(model=model, provider_options=options)
    result = ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "audio.wav", context(), lambda: False)
    assert result["sample_rate"] == 24000 and result["channels"] == 1
    assert result["duration"] == .1 and result["remote_request_id"] == "mock-123"
    assert "fixture-key" not in json.dumps(compiled) + json.dumps(result)


def test_snapshot_revalidated_before_network(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda req: pytest.fail("Invalid snapshots must not reach the API"))
    compiled = request()
    compiled["parameters"]["options"]["stability"] = .34
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "audio.wav", context(), lambda: False)
    assert error.value.code == "invalid_options"
    compiled = request()
    compiled["parameters"]["delivery"] = "whisper"
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "audio.wav", context(), lambda: False)
    assert error.value.code == "unsupported_intent"


@pytest.mark.parametrize("language", [
    "auto",
    "zh",
])
def test_v4_minimal_payload_preserves_script(monkeypatch, tmp_path, language):
    text = "[whispers] Hello. [long pause] 再见。"
    def handler(req):
        assert req.url.path == "/v1/text-to-speech/fixtureVoice123"
        expected = {"text": text, "model_id": "eleven_v4"}
        if language != "auto":
            expected["language_code"] = language
        assert json.loads(req.content) == expected
        return httpx.Response(200, content=wav())
    mock_http(monkeypatch, handler)
    compiled = request(model="eleven_v4", language=language)
    compiled["text"] = text
    ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "v4.wav", context(), lambda: False)
