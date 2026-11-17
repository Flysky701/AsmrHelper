import base64
from copy import deepcopy
from io import BytesIO
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.cloud_mimo import MimoSpeechProvider
from src.core.speech.providers import ProviderError


def recipe(**changes):
    value = {"provider_id": "mimo", "model": "mimo-v2.5-tts", "mode": "builtin", "connection_ref": "mimo-test",
        "variant": {"kind": "builtin", "value": "Chloe", "style": "normal"}, "language": "en",
        "provider_options": {"schema_version": 1}}
    value.update(changes)
    return value


def compiled(source=None, **segment):
    source = source or recipe()
    return {"provider_id": "mimo", "provider_version": "1", "model": source["model"], "mode": source["mode"],
        "connection_ref": source["connection_ref"], "text": "A small synthetic test.",
        "parameters": MimoSpeechProvider().compile(source, segment, "A small synthetic test.", {})}


def context(base="https://api.xiaomimimo.com/v1"):
    return {"connection": {"provider_id": "mimo", "base_url": base, "api_key": "synthetic-test-key", "timeout": 2}}


def wav():
    buffer = BytesIO()
    sf.write(buffer, np.sin(np.arange(2400) * .05) * .1, 24000, format="WAV")
    return buffer.getvalue()


def response(audio=None, finish_reason="stop"):
    return {"id": "test-completion", "choices": [{"finish_reason": finish_reason,
        "message": {"role": "assistant", "audio": {"data": audio if audio is not None else base64.b64encode(wav()).decode()}}}]}


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))


def test_mimo_contract_request_and_audio(monkeypatch, tmp_path):
    source = recipe(provider_options={"schema_version": 1, "style_description": "Read slowly."})
    request = compiled(source, delivery="whisper", emotion="calm")
    frozen = deepcopy(request)

    def handler(req):
        assert str(req.url) == "https://api.xiaomimimo.com/v1/chat/completions"
        assert req.headers["api-key"] == "synthetic-test-key"
        body = json.loads(req.content)
        assert body == {"model": "mimo-v2.5-tts", "stream": False, "audio": {"format": "wav", "voice": "Chloe"},
            "messages": [{"role": "user", "content": "Speak in English. Whisper the speech. Express a calm emotion. Read slowly."},
                         {"role": "assistant", "content": request["text"]}]}
        return httpx.Response(200, json=response(), headers={"x-request-id": "mimo-request"})

    mock_http(monkeypatch, handler)
    metadata = MimoSpeechProvider().synthesize(request, tmp_path / "mimo.wav", context(), lambda: False)
    assert metadata["sample_rate"] == 24000 and metadata["channels"] == 1
    assert metadata["duration"] == .1 and metadata["remote_request_id"] == "mimo-request"
    assert request == frozen
    assert "synthetic-test-key" not in json.dumps(request) + json.dumps(metadata)


@pytest.mark.parametrize("base", ["https://proxy.example/prefix/v1", "https://proxy.example/prefix/v1/chat/completions"])
def test_proxy_endpoint_auto_language_and_plain_text(monkeypatch, tmp_path, base):
    request = compiled(recipe(language="auto"))

    def handler(req):
        assert str(req.url) == "https://proxy.example/prefix/v1/chat/completions"
        assert json.loads(req.content)["messages"] == [{"role": "assistant", "content": request["text"]}]
        return httpx.Response(200, json=response())

    mock_http(monkeypatch, handler)
    MimoSpeechProvider().synthesize(request, tmp_path / "mimo.wav", context(base), lambda: False)


@pytest.mark.parametrize("change,code", [
    ({"model": "mimo-v2.5-tts-voiceclone"}, "invalid_model"),
    ({"model": "mimo-v2.5-tts-voicedesign"}, "invalid_model"),
    ({"mode": "reference"}, "invalid_mode"),
    ({"language": "ja"}, "invalid_language"),
    ({"variant": {"kind": "builtin", "value": "invented"}}, "invalid_variant"),
    ({"provider_options": {"schema_version": 1, "speed": 1.1}}, "invalid_options"),
    ({"provider_options": {"schema_version": 1, "temperature": .7}}, "invalid_options"),
])
def test_unsupported_features_fail_at_compile(change, code):
    with pytest.raises(ProviderError) as error:
        compiled(recipe(**change))
    assert error.value.code == code


@pytest.mark.parametrize("payload,code", [
    ({}, "invalid_audio"), ({"choices": []}, "invalid_audio"),
    (response("invalid-base64!"), "invalid_audio"), (response(""), "invalid_audio"),
    (response(base64.b64encode(b"not audio").decode()), "invalid_audio"),
    (response(finish_reason="length"), "incomplete_audio"),
    (response(finish_reason="content_filter"), "content_filtered"),
])
def test_invalid_results_are_not_saved(monkeypatch, tmp_path, payload, code):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    output = tmp_path / "bad.wav"
    with pytest.raises(ProviderError) as error:
        MimoSpeechProvider().synthesize(compiled(), output, context(), lambda: False)
    assert error.value.code == code
    assert not output.exists()


def test_invalid_snapshot_and_connection_fail_before_request(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda req: pytest.fail("must not send a request"))
    request = compiled()
    request["parameters"]["instruction"] = "Changed after compilation."
    with pytest.raises(ProviderError) as error:
        MimoSpeechProvider().synthesize(request, tmp_path / "a.wav", context(), lambda: False)
    assert error.value.code == "invalid_snapshot"
    invalid_context = context()
    invalid_context["connection"]["provider_id"] = "openai_compatible"
    with pytest.raises(ProviderError) as error:
        MimoSpeechProvider().synthesize(compiled(), tmp_path / "a.wav", invalid_context, lambda: False)
    assert error.value.code == "connection_mismatch"


def test_cancellation_and_timeout_do_not_retry(monkeypatch, tmp_path):
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("synthetic-test-key")

    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        MimoSpeechProvider().synthesize(compiled(), tmp_path / "a.wav", context(), lambda: True)
    assert error.value.code == "cancelled" and not calls
    with pytest.raises(ProviderError) as error:
        MimoSpeechProvider().synthesize(compiled(), tmp_path / "a.wav", context(), lambda: False)
    assert error.value.result_unknown and not error.value.retryable and len(calls) == 1
    assert "synthetic-test-key" not in str(error.value)


def test_catalog_and_capabilities_are_conservative():
    provider = MimoSpeechProvider()
    assert len(provider.voice_sources("builtin")["presets"]) == 9
    assert provider.voice_sources("builtin")["allow_custom"] is False
    assert provider.runtime_options("mimo-v2.5-tts", "builtin") == ["style_description"]
    assert provider.runtime_options("mimo-v2.5-tts-voiceclone", "reference") == []
    assert not provider.capabilities()["reference"]["supported"]
    assert not provider.capabilities()["streaming"]
    assert provider.capabilities()["emotion"]["evidence"] == "unverified"
