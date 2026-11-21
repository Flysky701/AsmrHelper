"""Shared cloud HTTP boundaries; every request stays inside MockTransport."""
from io import BytesIO

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.cloud_http import post_audio
from src.core.speech.providers import ProviderError


def install_transport(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))


def wav_bytes():
    buffer = BytesIO()
    sf.write(buffer, np.sin(np.arange(2400) / 20).astype("float32") * .1,
             24000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.mark.parametrize("failure,code,unknown", [
    (401, "authentication_failed", False),
    (402, "payment_required", False),
    ("timeout", "result_unknown", True),
])
def test_failures_never_retry_or_expose_upstream_secrets(tmp_path, monkeypatch, failure, code, unknown):
    secret = "fixture-secret-never-public"
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if failure == "network":
            raise httpx.ConnectError(secret, request=request)
        return httpx.Response(failure, text=secret)

    install_transport(monkeypatch, handler)
    output = tmp_path / "failed.wav"
    with pytest.raises(ProviderError) as caught:
        post_audio("https://speech.invalid/tts", {"api-key": secret},
                   {"text": "Fixture"}, output, {"timeout": 2})
    assert len(calls) == 1
    assert caught.value.code == code
    assert caught.value.result_unknown is unknown
    assert secret not in str(caught.value)
    assert secret not in str(caught.value.task_error)
    assert not output.exists()


@pytest.mark.parametrize("raw,encoding,rate", [
    (b"not audio", "audio", None),
])
def test_invalid_audio_cannot_be_published(tmp_path, monkeypatch, raw, encoding, rate):
    install_transport(monkeypatch, lambda request: httpx.Response(200, content=raw))
    path = tmp_path / "invalid.wav"
    with pytest.raises(ProviderError) as caught:
        post_audio("https://speech.invalid/tts", {}, {}, path, {"timeout": 2},
                   decoder=lambda response: (response.content, encoding, rate))
    assert caught.value.code == "invalid_audio"
    assert not path.exists()
