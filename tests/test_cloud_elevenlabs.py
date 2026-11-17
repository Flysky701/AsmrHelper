"""Offline contract tests; fixtures are generated audio, never a live API call."""
from io import BytesIO
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.cloud_elevenlabs import ElevenLabsSpeechProvider
from src.core.speech.providers import ProviderError


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


def wav():
    buffer = BytesIO()
    sf.write(buffer, np.full(2400, .1), 24000, format="WAV")
    return buffer.getvalue()


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("model,options,expected", [
    ("eleven_v3", {"schema_version": 1, "speed": .8}, {"speed": .8}),
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


def test_auto_language_omitted_and_proxy_prefix_preserved(monkeypatch, tmp_path):
    def handler(req):
        assert str(req.url).startswith("https://proxy.invalid/eleven/v1/text-to-speech/fixtureVoice123?")
        assert "language_code" not in json.loads(req.content)
        return httpx.Response(200, content=wav())
    mock_http(monkeypatch, handler)
    ElevenLabsSpeechProvider().synthesize(request(language="auto"), tmp_path / "audio.wav",
        context("https://proxy.invalid/eleven/v1"), lambda: False)


@pytest.mark.parametrize("changes,code", [
    ({"model": "eleven_v4_turbo"}, "invalid_model"),
    ({"model": "eleven_multilingual_v2"}, "invalid_model"),
    ({"language": "nonsense"}, "invalid_language"),
    ({"variant": {"kind": "hosted", "value": "../voices"}}, "invalid_variant"),
    ({"variant": {"kind": "hosted", "value": "voice", "style": "whisper"}}, "unsupported_intent"),
    ({"provider_options": {"schema_version": 1, "speed": 1.21}}, "invalid_options"),
    ({"provider_options": {"schema_version": 1, "stability": .5}}, "invalid_options"),
    ({"provider_options": {"schema_version": 1, "temperature": .5}}, "invalid_options"),
])
def test_unsupported_fields_rejected(changes, code):
    with pytest.raises(ProviderError) as error:
        request(**changes)
    assert error.value.code == code


def test_intent_and_length_limits():
    provider = ElevenLabsSpeechProvider()
    for segment in ({"emotion": "happy"}, {"delivery": "whisper"}):
        with pytest.raises(ProviderError) as error:
            provider.compile(recipe(), segment, "Test", {})
        assert error.value.code == "unsupported_intent"
    with pytest.raises(ProviderError) as error:
        provider.compile(recipe(), {}, "x" * 5001, {})
    assert error.value.code == "invalid_text"
    provider.compile(recipe(model="eleven_flash_v2_5"), {}, "x" * 5001, {})
    assert provider.runtime_options("eleven_v3", "hosted") == ["speed"]
    assert provider.runtime_options("eleven_flash_v2_5", "hosted") == ["speed", "stability"]


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (429, "rate_limited"),
    (404, "model_unavailable"), (500, "remote_failed"), (200, "invalid_audio")])
def test_safe_failures(monkeypatch, tmp_path, status, code):
    mock_http(monkeypatch, lambda req: httpx.Response(status, content=b"fixture-key"))
    output = tmp_path / "bad.wav"
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(request(), output, context(), lambda: False)
    assert error.value.code == code
    assert "fixture-key" not in str(error.value)
    assert not output.exists()


def test_timeout_does_not_retry_and_cancellation_does_not_start_request(monkeypatch, tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("fixture-key", request=req)
    mock_http(monkeypatch, handler)
    provider = ElevenLabsSpeechProvider()
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request(), tmp_path / "audio.wav", context(), lambda: False)
    assert error.value.result_unknown and len(calls) == 1
    assert "fixture-key" not in str(error.value)
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request(), tmp_path / "audio.wav", context(), lambda: True)
    assert error.value.code == "cancelled" and len(calls) == 1


def test_snapshot_revalidated_before_network(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda req: pytest.fail("Invalid snapshots must not reach the API"))
    compiled = request()
    compiled["parameters"]["options"]["stability"] = .5
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "audio.wav", context(), lambda: False)
    assert error.value.code == "invalid_options"
    compiled = request()
    del compiled["parameters"]["options"]["speed"]
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "audio.wav", context(), lambda: False)
    assert error.value.code == "snapshot_mismatch"


@pytest.mark.parametrize("language", ["auto", "zh", "en", "ja"])
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


@pytest.mark.parametrize("option,value", [("speed", 1), ("stability", .5),
    ("similarity_boost", .5), ("style", 0)])
def test_v4_rejects_unverified_settings_in_recipe_and_snapshot(monkeypatch, tmp_path, option, value):
    mock_http(monkeypatch, lambda req: pytest.fail("Unsupported v4 settings must not reach the API"))
    with pytest.raises(ProviderError) as error:
        request(model="eleven_v4", provider_options={"schema_version": 1, option: value})
    assert error.value.code == "invalid_options"
    compiled = request(model="eleven_v4")
    compiled["parameters"]["options"][option] = value
    with pytest.raises(ProviderError) as error:
        ElevenLabsSpeechProvider().synthesize(compiled, tmp_path / "v4.wav", context(), lambda: False)
    assert error.value.code == "invalid_options"


def test_v4_length_boundary_and_execution_revalidation(monkeypatch, tmp_path):
    provider = ElevenLabsSpeechProvider()
    value = recipe(model="eleven_v4")
    provider.compile(value, {}, "x" * 10000, {})
    with pytest.raises(ProviderError) as error:
        provider.compile(value, {}, "x" * 10001, {})
    assert error.value.code == "invalid_text"
    assert provider.capabilities("eleven_v4", "hosted")["max_text_length"] == 10000
    assert provider.runtime_options("eleven_v4", "hosted") == []
    assert provider.modes[0]["models"] == ["eleven_v3", "eleven_flash_v2_5", "eleven_v4"]
    assert request(model="eleven_v4")["parameters"]["options"] == {"schema_version": 1}
    mock_http(monkeypatch, lambda req: pytest.fail("Overlong snapshots must not reach the API"))
    compiled = request(model="eleven_v4")
    compiled["text"] = "x" * 10001
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled, tmp_path / "v4.wav", context(), lambda: False)
    assert error.value.code == "invalid_text"
