from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest
import soundfile as sf

from src.app.services.artifact_service import ArtifactService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.app.services.tts_engine_service import TtsEngineService
from src.core.speech.providers import ProviderError, get_provider
from src.core.speech.store import SpeechStore
from test_cloud_speech_transport import install_transport, wav_bytes


@pytest.mark.parametrize("mode", ["default", "reference"])
def test_local_drama3_runs_through_speech_adapter(monkeypatch, tmp_path, mode):
    audio = wav_bytes()
    calls = []

    def handler(request):
        assert request.url.host == "127.0.0.1"
        assert "authorization" not in request.headers
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": "fish_drama3"}]})
        calls.append(json.loads(request.content))
        assert request.url.path == "/v1/audio/speech"
        return httpx.Response(200, content=audio)

    service = SpeechService(store=SpeechStore(tmp_path / "library"),
                            tasks=TaskService(), artifacts=ArtifactService())
    facade = TtsEngineService(speech_service=service)
    install_transport(monkeypatch, handler)
    output = tmp_path / "take.wav"
    if mode == "default":
        facade.synthesize_text(
            text="Hello.", output_path=str(output), provider="fish_audio_local", model="fish_drama3",
            common_options={"voice": "default"},
        )
    else:
        reference = tmp_path / "original.wav"
        reference.write_bytes(audio)
        asset = service.store.create("assets", {
            "name": "Original", "path": str(reference), "transcript": "Reference transcript",
            "sha256": hashlib.sha256(audio).hexdigest(), "confirmed": True,
        })
        voice = service.store.create("voices", {"name": "Clone", "bindings": []})
        recipe = service.save_recipe({
            "name": "Clone rule", "voice_id": voice["id"], "provider_id": "fish_audio_local",
            "model": "fish_drama3", "mode": "reference", "language": "auto",
            "variant": {"kind": "reference", "value": asset["id"]},
            "provider_options": {"schema_version": 1},
        })
        facade.synthesize_text(
            text="Hello.", output_path=str(output), recipe_id=recipe["id"],
        )
    assert sf.info(output).frames > 0
    assert len(calls) == 1
    assert calls[0]["model"] == "fish_drama3" and calls[0]["input"] == "Hello."
    if mode == "reference":
        [ref] = calls[0]["references"]
        assert ref["text"] == "Reference transcript"
        assert base64.b64decode(ref["data"]) == audio
    else:
        assert "references" not in calls[0]


def test_local_drama3_rejects_remote_urls_and_unrelated_running_models(monkeypatch):
    provider = get_provider("fish_audio_local")
    with pytest.raises(ProviderError, match="回环"):
        provider.connection_base({"base_url": "https://other-service.invalid/v1"})
    base = provider.connection_base({"base_url": "http://localhost:4321/v1/audio/speech/"})
    assert base == "http://127.0.0.1:4321/v1"
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "unrelated"}]}))
    result = provider.probe({"connection": {"base_url": base}})
    assert result["ready"] is False
    assert result["code"] == "model_mismatch"
