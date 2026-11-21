import base64
from copy import deepcopy
import json

import httpx
import pytest

from src.core.speech.cloud_mimo import MimoSpeechProvider
from src.core.speech.providers import ProviderError
from test_cloud_speech_transport import install_transport as mock_http, wav_bytes as wav


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


def response(audio=None, finish_reason="stop"):
    return {"id": "test-completion", "choices": [{"finish_reason": finish_reason,
        "message": {"role": "assistant", "audio": {"data": audio if audio is not None else base64.b64encode(wav()).decode()}}}]}


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
