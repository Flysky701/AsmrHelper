"""VoiceLab HTTP → dispatcher → native protocol → durable take integration."""
from io import BytesIO
import json
import time

from fastapi.testclient import TestClient
import httpx
import numpy as np
import pytest
import soundfile as sf

from src.api.http.app import create_app
from src.api.http import dependencies
from src.app.services.speech_service import SpeechService, get_speech_service
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech.store import SpeechStore


@pytest.fixture
def speech_http(tmp_path):
    service = SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=TaskService(), artifacts=ArtifactService())
    app = create_app()
    app.dependency_overrides[get_speech_service] = lambda: service
    app.dependency_overrides[dependencies.task_service] = lambda: service.tasks
    app.dependency_overrides[dependencies.task_dispatcher] = lambda: service.dispatcher
    app.dependency_overrides[dependencies.artifact_service] = lambda: service.artifacts
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, service
    app.dependency_overrides.clear()


def post(client, path, body, status=200):
    response = client.post("/api/v1/speech" + path, json=body)
    assert response.status_code == status, response.text
    return response.json()


def setup_fish(client):
    connection = post(client, "/connections", {"name": "Fish test", "provider_id": "fish_audio", "deployment": "cloud",
        "base_url": "https://fish.invalid/v1", "api_key": "never-expose-this-key"})
    voice = post(client, "/voices", {"name": "测试声音", "bindings": []})
    recipe = post(client, "/recipes", {"name": "测试配方", "voice_id": voice["id"], "provider_id": "fish_audio",
        "model": "s2-pro", "mode": "hosted", "connection_ref": connection["id"],
        "variant": {"kind": "hosted", "value": "voice-native-id", "style": "normal"},
        "language": "zh", "provider_options": {"schema_version": 1}})
    plan = post(client, "/plans", {"text": "第一句。第二句。"})
    experiment = post(client, "/experiments", {"name": "真实任务测试", "plan_id": plan["id"]})
    return connection, voice, recipe, plan, experiment


def wait_task(client, task_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get("/api/v1/tasks/" + task_id)
        assert response.status_code == 200, response.text
        state = response.json()
        if state["state"] in {"completed", "failed", "cancelled"}:
            return state
        time.sleep(.02)
    pytest.fail("speech dispatcher did not finish")


def wav():
    buffer = BytesIO()
    sf.write(buffer, np.sin(np.arange(2400) / 20).astype("float32") * .1, 24000, format="WAV")
    return buffer.getvalue()


def test_browser_reference_upload_can_be_cropped_and_played(speech_http):
    client, service = speech_http
    response = client.post("/api/v1/speech/references/upload", params={"filename": "参考.wav"},
        content=wav(), headers={"content-type": "application/octet-stream"})
    assert response.status_code == 200, response.text
    inspection = response.json()
    assert inspection["duration"] == pytest.approx(.1)
    assert not list((service.store.root / "_uploads").iterdir())
    asset = post(client, "/references", {"path": inspection["path"], "start": 0, "end": .08,
        "transcript": "测试", "language": "zh", "confirmed": True})
    audio = client.get(f'/api/v1/speech/references/{asset["id"]}/audio')
    samples, rate = sf.read(BytesIO(audio.content))
    assert len(samples) == int(rate * .08)


def test_browser_reference_upload_rejects_empty_and_oversize(speech_http, monkeypatch):
    client, service = speech_http
    assert client.post("/api/v1/speech/references/upload?filename=empty.wav", content=b"").status_code == 422
    assert client.post("/api/v1/speech/references/upload?filename=bad.exe", content=b"bad").status_code == 422
    monkeypatch.setattr("src.api.http.routes.speech.MAX_REFERENCE_UPLOAD", 3)
    assert client.post("/api/v1/speech/references/upload?filename=large.wav", content=b"1234").status_code == 413
    # Missing Content-Length: enforce the limit while streaming too.
    assert client.post("/api/v1/speech/references/upload?filename=large.wav", content=iter([b"12", b"34"])).status_code == 413
    assert not list((service.store.root / "_uploads").iterdir())


def test_reference_metadata_patch_is_allowed_from_desktop_origin(speech_http):
    client, _ = speech_http
    response = client.options("/api/v1/speech/references/test", headers={
        "origin": "http://tauri.localhost", "access-control-request-method": "PATCH",
        "access-control-request-headers": "content-type",
    })
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_reference_library_preview_search_archive_and_subtitles(speech_http):
    client, service = speech_http
    uploaded = client.post("/api/v1/speech/references/upload?filename=sample.wav", content=wav()).json()
    body = {"path": uploaded["path"], "start": 0, "end": .08, "name": "雨声", "notes": "素材备注", "gain_db": -3, "fade_in": .01, "fade_out": .01}
    preview = post(client, "/references/preview", body)
    assert service.store.list("assets") == []
    saved = post(client, "/references", body)
    assert saved["sha256"] == preview["sha256"] and saved["confirmed"] is False
    assert client.get(f'/api/v1/speech/references/{preview["id"]}/audio').status_code == 200
    assert client.get("/api/v1/speech/references?query=备注").json()["assets"][0]["id"] == saved["id"]
    changed = client.patch(f'/api/v1/speech/references/{saved["id"]}', json={"name": "新名"})
    assert changed.status_code == 200 and changed.json()["sha256"] == saved["sha256"]
    assert client.delete(f'/api/v1/speech/references/{saved["id"]}').status_code == 200
    assert client.get("/api/v1/speech/references").json()["assets"] == []
    assert client.get(f'/api/v1/speech/references/{saved["id"]}/audio').status_code == 200
    cues = post(client, "/references/subtitles", {"format": "vtt", "text": "WEBVTT\n\n00:00.100 --> 00:00.800\n测试\n"})
    assert cues["segments"] == [{"start": .1, "end": .8, "text": "测试"}]


def test_rule_archive_restore_http_preserves_original_records(speech_http):
    client, service = speech_http
    _, _, first, _, _ = setup_fish(client)
    second = service.store.update("recipes", first["id"], {"name": "最新版本"})
    base = "/api/v1/speech/rules"
    assert client.delete(f'{base}/{second["id"]}').status_code == 200
    assert client.get(base).json()["recipes"] == []
    assert client.get(base + "?include_archived=true").json()["recipes"] == [{**second, "archived": True}]
    assert client.patch(f'{base}/{first["id"]}', json={"archived": "false"}).status_code == 422
    response = client.patch(f'{base}/{first["id"]}', json={"archived": False})
    assert response.status_code == 200 and response.json()["archived"] is False
    assert client.get(base).json()["recipes"] == [second]
    assert service.store.get("recipes", first["id"]) == first
    assert service.store.get("recipes", second["id"]) == second


def fake_remote(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))


def test_fish_http_task_candidates_selection_and_partial_regeneration(speech_http, monkeypatch):
    client, service = speech_http
    calls = []
    def handler(request):
        assert str(request.url) == "https://fish.invalid/v1/tts"
        assert request.headers["model"] == "s2-pro"
        assert request.headers["authorization"] == "Bearer never-expose-this-key"
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wav(), headers={"x-request-id": "fake-result"})
    fake_remote(monkeypatch, handler)
    _, _, recipe, plan, experiment = setup_fish(client)
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"]}, status=202)
    result = wait_task(client, task["task_id"])
    assert result["state"] == "completed", result
    takes = client.get(f"/api/v1/speech/experiments/{experiment['id']}").json()["takes"]
    assert len(takes) == 2 and len(calls) == 2
    assert [call["text"] for call in calls] == ["第一句。", "第二句。"]
    for take in takes:
        audio = client.get(f"/api/v1/speech/takes/{take['id']}/audio")
        assert audio.status_code == 200 and sf.info(BytesIO(audio.content)).samplerate == 24000
        post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": take["segment_id"], "take_id": take["id"]})
    first = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    rendered = client.get(f"/api/v1/speech/assemblies/{first['id']}/audio")
    assert rendered.status_code == 200 and sf.info(BytesIO(rendered.content)).frames > 0
    task2 = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"], "segment_id": takes[0]["segment_id"]}, status=202)
    assert wait_task(client, task2["task_id"])["state"] == "completed"
    new_takes = service.experiment(experiment["id"])["takes"]
    replacement = next(t for t in new_takes if t["task_id"] == task2["task_id"])
    post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": replacement["segment_id"], "take_id": replacement["id"]})
    second = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    assert first["processing"][1]["take_id"] == second["processing"][1]["take_id"]
    assert first["processing"][0]["take_id"] != second["processing"][0]["take_id"]
    assert len(calls) == 3 and len(new_takes) == 3
    assert "never-expose-this-key" not in client.get("/api/v1/speech/library").text
    assert "never-expose-this-key" not in json.dumps(service.tasks.get_task_spec(task["task_id"]).execution_profile)


def test_remote_result_unknown_is_structured_and_generic_retry_blocked(speech_http, monkeypatch):
    client, service = speech_http
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("never-expose-this-key")
    fake_remote(monkeypatch, handler)
    _, _, recipe, _, experiment = setup_fish(client)
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"]}, status=202)
    result = wait_task(client, task["task_id"])
    assert result["state"] == "failed" and result["error"]["result_unknown"] is True
    assert result["error"]["retryable"] is False
    assert "never-expose-this-key" not in json.dumps(result)
    retry = client.post(f"/api/v1/tasks/{task['task_id']}/retry")
    assert retry.status_code in {400, 409, 422}, retry.text
    assert len(calls) == 1 and service.store.list("takes") == []


@pytest.mark.parametrize("path", ["/compile", "/plan-performance", "/references", "/references/inspect", "/experiments", "/workbench-draft"])
def test_missing_http_fields_are_validation_errors(speech_http, path):
    client, _ = speech_http
    response = client.post("/api/v1/speech" + path, json={})
    assert response.status_code == 422, response.text


def test_recipe_requires_existing_voice(speech_http):
    client, _ = speech_http
    _, _, recipe, _, _ = setup_fish(client)
    recipe.pop("id")
    recipe["voice_id"] = "nonexistent-voice"
    response = client.post("/api/v1/speech/recipes", json=recipe)
    assert response.status_code == 422, response.text


def test_formal_fish_single_sentence_regeneration_preserves_other_audio(speech_http, monkeypatch, tmp_path):
    client, service = speech_http
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=wav())
    fake_remote(monkeypatch, handler)
    _, _, recipe, _, _ = setup_fish(client)
    first = service.synthesize_timeline(service.snapshot(recipe["id"]), [
        {"text": "第一句。", "start_time": .2, "end_time": .5},
        {"text": "第二句。", "start_time": .8, "end_time": 1.1},
    ], tmp_path / "formal.wav", "formal-parent", reference_duration=1.5)
    experiment = next(e for e in service.store.list("experiments") if e.get("kind") == "formal")
    task = post(client, f"/experiments/{experiment['id']}/generate", {"recipe_id": recipe["id"], "segment_id": "sentence-1"}, status=202)
    assert wait_task(client, task["task_id"])["state"] == "completed"
    take = next(t for t in service.experiment(experiment["id"])["takes"] if t["task_id"] == task["task_id"])
    post(client, "/selections", {"experiment_id": experiment["id"], "segment_id": "sentence-1", "take_id": take["id"]})
    second = post(client, "/assemblies", {"experiment_id": experiment["id"]})
    assert len(calls) == 3
    assert first["processing"][1]["take_id"] == second["processing"][1]["take_id"]
    assert first["processing"][0]["take_id"] != second["processing"][0]["take_id"]
    assert second["duration"] == 1.5


def test_recipe_rejects_binding_provider_mismatch(speech_http):
    client, _ = speech_http
    _, _, recipe, _, _ = setup_fish(client)
    voice = post(client, "/voices", {"name": "Edge only", "bindings": [{"id": "edge", "provider_id": "edge", "variants": []}]})
    recipe.pop("id")
    recipe["voice_id"] = voice["id"]
    response = client.post("/api/v1/speech/recipes", json=recipe)
    assert response.status_code == 422, response.text
