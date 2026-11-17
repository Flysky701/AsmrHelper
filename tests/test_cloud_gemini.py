"""Offline Gemini REST contract fixtures; no credentials or external requests."""
from copy import deepcopy
from io import BytesIO
import base64
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.cloud_gemini import GeminiSpeechProvider, MODELS, VOICES
from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.providers import ProviderError


@pytest.fixture
def provider():
    from src.core.speech import providers
    return providers.get_provider("gemini")


def recipe(**changes):
    result = {"id": "gemini-recipe", "revision": 1, "provider_id": "gemini",
              "model": MODELS[0], "mode": "builtin", "connection_ref": "gemini-connection",
              "variant": {"kind": "builtin", "value": "Kore", "style": "normal"},
              "language": "zh", "provider_options": {"schema_version": 1}}
    result.update(changes)
    return result


def compiled(source=None, **segment):
    text = "你好。 <short pause> Hello."
    return compile_recipe(source or recipe(), {"text": text, "text_hash": text_hash(text),
        "segments": [{"id": "line", "start": 0, "end": len(text),
                      "delivery": "normal", "emotion": "neutral", "pause_ms": 0, **segment}]}, {})[0]


def context(**changes):
    return {"connection": {"provider_id": "gemini", "base_url": GeminiSpeechProvider.default_base_url,
                           "api_key": "fixture-key", **changes}}


def audio_bytes():
    buffer = BytesIO()
    sf.write(buffer, np.linspace(-.2, .2, 2400), 24000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def response_body(content=None, mime="audio/wav"):
    return {"status": "completed", "steps": [
        {"type": "user_input", "content": [{"type": "audio", "data": "ignored"}]},
        {"type": "model_output", "content": [{"type": "audio", "mime_type": mime,
         "data": base64.b64encode(audio_bytes() if content is None else content).decode()}]}]}


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("model", MODELS)
def test_native_interactions_request_and_wav(provider, monkeypatch, tmp_path, model):
    source = recipe(model=model, provider_options={"schema_version": 1, "style_description": "warm and friendly"})
    request = compiled(source, delivery="whisper", emotion="calm")
    before = deepcopy(request)

    def handler(req):
        assert str(req.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert req.headers["x-goog-api-key"] == "fixture-key"
        assert "authorization" not in req.headers
        body = json.loads(req.content)
        assert body["model"] == model
        assert body["stream"] is False and body["store"] is False
        assert body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
        assert body["response_format"] == {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000}
        part = body["input"][0]["content"][0]
        assert part["text"] == request["text"]
        assert part["annotations"] == [{"type": "speech_metadata", "style": "warm and friendly; whispering; calm"}]
        assert "language" not in body  # documented automatic language detection
        return httpx.Response(200, json=response_body(), headers={"x-request-id": "gemini-fixture"})

    mock_http(monkeypatch, handler)
    metadata = provider.synthesize(request, tmp_path / "audio.wav", context(), lambda: False)
    assert metadata["sample_rate"] == 24000 and metadata["channels"] == 1 and metadata["duration"] == .1
    assert metadata["remote_request_id"] == "gemini-fixture"
    assert request == before and "fixture-key" not in json.dumps(request)


def test_hosted_voice_and_proxy_endpoint_preserved(provider, monkeypatch, tmp_path):
    request = compiled(recipe(mode="hosted", variant={"kind": "hosted", "value": "voice_fixture-123"}))

    def handler(req):
        assert str(req.url) == "https://proxy.invalid/google/v1beta/interactions"
        body = json.loads(req.content)
        assert body["generation_config"]["speech_config"] == [{"voice": "voice_fixture-123"}]
        assert "annotations" not in body["input"][0]["content"][0]
        return httpx.Response(200, json=response_body())

    mock_http(monkeypatch, handler)
    provider.synthesize(request, tmp_path / "voice.wav", context(base_url="https://proxy.invalid/google/v1beta/interactions"), None)


def test_declared_pcm_response_decoded_little_endian(provider, monkeypatch, tmp_path):
    pcm = np.array([1000, -1000, 32767, -32768], dtype="<i2").tobytes()
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=response_body(pcm, "audio/l16;rate=24000;channels=1")))
    output = tmp_path / "pcm.wav"
    result = provider.synthesize(compiled(), output, context(), None)
    assert result["sample_rate"] == 24000
    samples, _ = sf.read(output, dtype="int16")
    np.testing.assert_array_equal(samples, [1000, -1000, 32767, -32768])


@pytest.mark.parametrize("body", [
    {}, {"steps": []}, {"steps": "malformed"},
    {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": "not base64"}]}]},
    response_body(b"garbage"), response_body(b"\x00", "audio/l16"),
    response_body(b"\x00\x00", "audio/l16;rate=16000"),
    response_body(b"\x00\x00", "audio/l16;channels=2"),
    response_body(b"\x00\x00", "audio/mulaw"),
])
def test_malformed_audio_rejected_without_output(provider, monkeypatch, tmp_path, body):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    output = tmp_path / "bad.wav"
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled(), output, context(), None)
    assert error.value.code == "invalid_audio" and not output.exists()


@pytest.mark.parametrize("status", ["in_progress", "incomplete", "failed", "cancelled"])
def test_incomplete_unary_result_is_not_success(provider, monkeypatch, tmp_path, status):
    body = response_body()
    body["status"] = status
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled(), tmp_path / "bad.wav", context(), None)
    assert error.value.code == "remote_incomplete" and error.value.result_unknown


@pytest.mark.parametrize("changes,code", [
    ({"model": "gemini-2.5-pro-preview-tts"}, "invalid_model"),
    ({"provider_options": {"schema_version": 1, "temperature": .5}}, "invalid_options"),
    ({"variant": {"kind": "builtin", "value": "made-up-voice"}}, "invalid_variant"),
    ({"mode": "hosted", "variant": {"kind": "hosted", "value": "voicekey_temporary"}}, "invalid_variant"),
    ({"language": "th"}, "invalid_language"),
])
def test_model_voice_language_and_options_fail_closed(provider, changes, code):
    with pytest.raises(ProviderError) as error:
        compiled(recipe(**changes))
    assert error.value.code == code


def test_metadata_and_snapshot_are_stable(provider):
    description = provider.describe()
    assert len(VOICES) == 30 and description["capabilities"]["streaming"] is False
    assert description["capabilities"]["language_control"] == "automatic"
    assert provider.runtime_options(MODELS[0], "builtin") == ["style_description"]
    assert provider.runtime_options("unverified-model", "builtin") == []
    initial = recipe()
    assert compiled(initial) == compiled(json.loads(json.dumps(initial)))
    changed = recipe(provider_options={"schema_version": 1, "style_description": "cheerful"})
    assert compiled(initial)["cache_key"] != compiled(changed)["cache_key"]


def test_variant_style_is_a_voice_label_and_frozen_model_is_revalidated(provider, monkeypatch, tmp_path):
    request = compiled(recipe(variant={"kind": "builtin", "value": "Kore", "style": "whisper"}))
    assert request["parameters"]["delivery"] == "normal"
    request["model"] = "unknown-future-model"
    mock_http(monkeypatch, lambda req: pytest.fail("invalid snapshot must not reach the network"))
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request, tmp_path / "out.wav", context(), None)
    assert error.value.code == "invalid_model"


@pytest.mark.parametrize("change", ["unknown_field", "missing_delivery"])
def test_tampered_snapshot_parameters_prevent_request(provider, monkeypatch, tmp_path, change):
    request = compiled()
    if change == "unknown_field":
        request["parameters"]["unrecognized_parameter"] = "must not be silently dropped"
    else:
        del request["parameters"]["delivery"]
    mock_http(monkeypatch, lambda req: pytest.fail("invalid snapshot must not reach the network"))
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request, tmp_path / "out.wav", context(), None)
    assert error.value.code == "invalid_snapshot"


def test_timeout_and_cancel_do_not_retry(provider, monkeypatch, tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("fixture-key")
    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled(), tmp_path / "out.wav", context(), None)
    assert error.value.result_unknown and len(calls) == 1 and "fixture-key" not in str(error.value)
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled(), tmp_path / "out.wav", context(), lambda: True)
    assert error.value.code == "cancelled" and len(calls) == 1
