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
    (401, "authentication_failed", False), (402, "payment_required", False),
    (429, "rate_limited", False), (500, "remote_failed", True),
    ("timeout", "result_unknown", True), ("network", "connection_failed", True),
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


@pytest.mark.parametrize("encoding", ["audio", "pcm_s16le"])
def test_success_normalizes_audio_and_preserves_request_id(tmp_path, monkeypatch, encoding):
    raw = wav_bytes() if encoding == "audio" else np.arange(2400, dtype="<i2").tobytes()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=raw, headers={"x-request-id": "fixture-request"})

    install_transport(monkeypatch, handler)
    path = tmp_path / "audio.wav"
    request_id = post_audio("https://speech.invalid/tts?output_format=wav_24000", {}, {}, path,
                           {"timeout": 2}, decoder=lambda response: (response.content, encoding, 24000))
    info = sf.info(path)
    assert (info.frames, info.samplerate, info.channels, info.subtype) == (2400, 24000, 1, "PCM_16")
    assert request_id == "fixture-request"
    assert len(calls) == 1 and calls[0].url.params["output_format"] == "wav_24000"


@pytest.mark.parametrize("raw,encoding,rate", [(b"not audio", "audio", None),
                                             (b"\x00", "pcm_s16le", 24000),
                                             (b"\x00\x00", "pcm_s16le", None)])
def test_invalid_audio_cannot_be_published(tmp_path, monkeypatch, raw, encoding, rate):
    install_transport(monkeypatch, lambda request: httpx.Response(200, content=raw))
    path = tmp_path / "invalid.wav"
    with pytest.raises(ProviderError) as caught:
        post_audio("https://speech.invalid/tts", {}, {}, path, {"timeout": 2},
                   decoder=lambda response: (response.content, encoding, rate))
    assert caught.value.code == "invalid_audio"
    assert not path.exists()
