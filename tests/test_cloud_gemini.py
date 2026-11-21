"""Offline Gemini REST contract fixtures; no credentials or external requests."""
from copy import deepcopy
from io import BytesIO
import base64
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.cloud_gemini import GeminiSpeechProvider, MODELS
from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.providers import ProviderError
from test_cloud_speech_transport import install_transport as mock_http


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


def test_declared_pcm_response_decoded_little_endian(provider, monkeypatch, tmp_path):
    pcm = np.array([1000, -1000, 32767, -32768], dtype="<i2").tobytes()
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=response_body(pcm, "audio/l16;rate=24000;channels=1")))
    output = tmp_path / "pcm.wav"
    result = provider.synthesize(compiled(), output, context(), None)
    assert result["sample_rate"] == 24000
    samples, _ = sf.read(output, dtype="int16")
    np.testing.assert_array_equal(samples, [1000, -1000, 32767, -32768])


@pytest.mark.parametrize("status", [
    "incomplete",
])
def test_incomplete_unary_result_is_not_success(provider, monkeypatch, tmp_path, status):
    body = response_body()
    body["status"] = status
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ProviderError) as error:
        provider.synthesize(compiled(), tmp_path / "bad.wav", context(), None)
    assert error.value.code == "remote_incomplete" and error.value.result_unknown
