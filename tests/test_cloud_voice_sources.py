"""Wire-level checks for provider-specific library voices and reference recordings."""
import base64
import hashlib
import json

import httpx
import msgpack
import pytest

from src.core.speech.providers import get_provider
from src.core.speech.voice_catalog import list_account_voices
from test_cloud_mimo import mock_http, response, wav


@pytest.mark.parametrize("provider,base,header,path,cursor,record", [
    ("gemini", "https://fixture.test/v1beta", "x-goog-api-key", "/v1beta/voices", "page_token",
     {"id": "library-5", "display_name": "Evening"}),
    ("elevenlabs", "https://fixture.test/v1", "xi-api-key", "/v2/voices", "next_page_token",
     {"voice_id": "library-5", "name": "Evening"}),
])
def test_account_voice_lookup_preserves_provider_cursor(monkeypatch, provider, base, header, path, cursor, record):
    def get(req):
        assert req.method == "GET" and req.url.path == path and req.headers[header] == "fixture"
        assert dict(req.url.params) == {"search": "eve", "page_size": "20", cursor: "previous"}
        return httpx.Response(200, json={"voices": [record], "has_more": True, "next_page_token": "next"})
    mock_http(monkeypatch, get)
    page = list_account_voices({"provider_id": provider, "api_key": "fixture", "base_url": base},
                              title="eve", page_size=20, page_token="previous")
    assert page["items"] == [{"id": "library-5", "name": "Evening"}]
    assert page["next_page_token"] == "next" and page["has_more"]


@pytest.mark.parametrize("provider,model,mode", [
    ("mimo", "mimo-v2.5-tts-voiceclone", "reference"),
    ("mimo", "mimo-v2.5-tts-voicedesign", "design"),
    ("fish_audio", "s2-pro", "reference"),
])
def test_voice_conditioning_uses_native_wire_format(monkeypatch, tmp_path, provider, model, mode):
    engine = get_provider(provider)
    clip = tmp_path / "reference.wav"
    raw = wav()
    clip.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    assets = {"clip": {"sha256": sha, "path": str(clip), "transcript": "Hello there.", "confirmed": True}}
    recipe = {"provider_id": provider, "model": model, "connection_ref": "fixture", "mode": mode,
              "variant": {"kind": mode, "value": "clip" if mode == "reference" else "A warm low voice."},
              "language": "auto", "provider_options": {"schema_version": 1}}
    text = "Good evening."
    request = {**recipe, "text": text, "parameters": engine.compile(recipe, {}, text, assets),
               "asset_hashes": {"clip": sha} if mode == "reference" else {}}
    def post(req):
        if provider == "fish_audio":
            assert req.headers["content-type"] == "application/msgpack" and req.headers["model"] == model
            body = msgpack.unpackb(req.content, raw=False)
            assert body["references"] == [{"audio": raw, "text": "Hello there."}] and "reference_id" not in body
            return httpx.Response(200, content=raw)
        body = json.loads(req.content)
        assert body["model"] == model and body["messages"][-1] == {"role": "assistant", "content": text}
        if mode == "reference":
            assert body["audio"]["voice"] == "data:audio/wav;base64," + base64.b64encode(raw).decode()
        else:
            assert "voice" not in body["audio"]
            assert body["messages"][0] == {"role": "user", "content": "A warm low voice."}
        return httpx.Response(200, json=response())
    mock_http(monkeypatch, post)
    engine._remote(request, tmp_path / "result.wav", {"assets": assets, "connection": {
        "provider_id": provider, "base_url": "https://fixture.test/v1", "api_key": "fixture"}})
    assert (tmp_path / "result.wav").is_file()
