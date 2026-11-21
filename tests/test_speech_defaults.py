"""Starter preset lifecycle; all audio generation is mocked, no network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api.http.routes.speech import router
from src.app.services.speech_service import SpeechService, get_speech_service
from src.core.speech.defaults import edge_starter_recipe
from src.core.speech.store import SpeechStore


def service(root):
    return SpeechService(store=SpeechStore(root), tasks=SimpleNamespace(history_deletion_guard=nullcontext, history_snapshot=lambda: []),
                         dispatcher=SimpleNamespace(register_executor=lambda *args: None, history_deletion_guard=nullcontext, has_live_worker=lambda _: False),
                         artifacts=SimpleNamespace(history_deletion_guard=nullcontext, list_records=lambda: []))


def test_nonempty_library_is_preserved_and_concurrent_initialization_is_idempotent(tmp_path):
    svc = service(tmp_path)
    existing = svc.save_rule({**edge_starter_recipe(), "name": "用户自己的音色"})
    before = deepcopy(existing)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: service(tmp_path).active_recipes(), range(8)))
    assert len(svc.active_recipes()) == 2
    assert svc.store.get("recipes", existing["id"]) == before


@pytest.mark.parametrize("first_entry", ["/speech/rules", "/speech/library"])
def test_http_list_delete_restart_readd_share_ordinary_recipe(tmp_path, monkeypatch, first_entry):
    monkeypatch.setattr("src.app.services.preset_catalog_service.get_preset_catalog_service", lambda: SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: []))
    svc = service(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_speech_service] = lambda: svc
    with TestClient(app) as client:
        first = client.get(first_entry).json()["recipes"]
        assert len(first) == 1
        recipe = first[0]
        assert recipe["variant"]["value"] == "zh-CN-XiaoxiaoNeural"
        assert client.get("/speech/rules").json()["recipes"][0]["id"] == recipe["id"]
        assert client.get("/speech/library").json()["recipes"][0]["id"] == recipe["id"]
        preview = client.post("/speech/cleanup/recipes/" + recipe["id"] + "/preview").json()
        assert client.delete("/speech/rules/" + recipe["id"], params={"token": preview["token"], "confirmed": True}).status_code == 200
        svc = service(tmp_path)
        assert client.get("/speech/rules").json()["recipes"] == []
        assert client.get("/speech/library").json()["recipes"] == []
        response = client.post("/speech/default-preset/add")
        assert response.status_code == 200
        assert response.json()["id"] != recipe["id"]
        assert len(client.get("/speech/rules").json()["recipes"]) == 1
