"""Starter preset lifecycle; all audio generation is mocked, no network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import nullcontext
from src.app.services.speech_cleanup_service import SpeechCleanupService
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest
import soundfile as sf

from src.api.http.routes.speech import router
from src.app.services.speech_service import SpeechService, get_speech_service
from src.core.speech.compiler import compile_recipe
from src.core.speech.defaults import EDGE_STARTER_KEY, edge_starter_recipe
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore, build_plan


def service(root):
    return SpeechService(store=SpeechStore(root), tasks=SimpleNamespace(history_deletion_guard=nullcontext, history_snapshot=lambda: []),
                         dispatcher=SimpleNamespace(register_executor=lambda *args: None, history_deletion_guard=nullcontext, has_live_worker=lambda _: False),
                         artifacts=SimpleNamespace(history_deletion_guard=nullcontext, list_records=lambda: []))


def test_empty_library_seeds_once_and_restart_keeps_identity(tmp_path):
    svc = service(tmp_path)
    first = svc.library()["recipes"]
    assert len(first) == 1
    recipe = first[0]
    assert recipe["provider_id"] == "edge"
    assert recipe["variant"]["value"] == "zh-CN-XiaoxiaoNeural"
    assert recipe["voice_id"] != recipe["variant"]["value"]
    assert recipe["provider_options"] == {"schema_version": 1, "speed": 1}
    assert recipe["connection_ref"] == "engine-default-edge"
    assert svc.active_recipes() == service(tmp_path).active_recipes() == first
    assert svc.store.connection_catalog() == ([], [])


def test_nonempty_library_is_preserved_and_concurrent_initialization_is_idempotent(tmp_path):
    svc = service(tmp_path)
    existing = svc.save_rule({**edge_starter_recipe(), "name": "用户自己的音色"})
    before = deepcopy(existing)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: service(tmp_path).active_recipes(), range(8)))
    assert len(svc.active_recipes()) == 2
    assert svc.store.get("recipes", existing["id"]) == before


def test_edit_copy_delete_restart_and_explicit_readd(tmp_path):
    svc = service(tmp_path)
    original = svc.active_recipes()[0]
    edited = svc.save_rule({**original, "name": "我的晓晓", "provider_options": {"schema_version": 1, "speed": .9}})
    assert svc.ensure_default_preset(add=True) == edited
    copied = svc.save_rule({**edge_starter_recipe(), "name": "晓晓副本"})
    assert copied["voice_id"] != original["voice_id"]
    cleanup = SpeechCleanupService(svc, SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: []))
    preview = cleanup.preview("recipes", edited["id"])
    cleanup.execute("recipes", edited["id"], preview["token"], True)
    restarted = service(tmp_path)
    assert [item["id"] for item in restarted.active_recipes()] == [copied["id"]]
    restored = restarted.ensure_default_preset(add=True)
    assert restored["id"] != edited["id"]
    assert restored["name"] == edge_starter_recipe()["name"]
    assert all(row["id"] != edited["id"] for row in restarted.store.list("recipes"))
    assert len(restarted.active_recipes()) == 2
    assert restarted.ensure_default_preset(add=True) == restored


def test_physical_removal_keeps_seed_marker_until_explicit_readd(tmp_path):
    svc = service(tmp_path)
    first = svc.active_recipes()[0]
    # Model the existing cleanup transaction, without touching real user data.
    with svc.store._locked():
        state = svc.store._read()
        state["collections"]["recipes"].pop(first["id"])
        svc.store._write(state)
    assert service(tmp_path).active_recipes() == []
    restored = service(tmp_path).ensure_default_preset(add=True)
    assert restored["id"] != first["id"]
    assert restored["variant"] == first["variant"]
    assert len(service(tmp_path).active_recipes()) == 1
    assert svc.store._read()["builtin_recipes"][EDGE_STARTER_KEY]["recipe_id"] == restored["id"]


def test_catalog_compile_and_mock_engine_receive_real_speaker_id(tmp_path, monkeypatch):
    svc = service(tmp_path / "store")
    recipe = svc.active_recipes()[0]
    monkeypatch.setattr("src.core.speech.providers.SpeechProvider.probe", lambda *args: {"ready": True})
    snapshot = svc.pipeline_snapshot({"provider": "edge", "model": "edge-tts",
                                     "options": {"speech_recipe_id": recipe["id"]}})
    request = compile_recipe(snapshot["recipe"], build_plan("中文试听。"), {})[0]
    calls = []

    class MockEdge:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def synthesize(self, text, path):
            calls.append(text)
            sf.write(path, np.zeros(240), 24000)

    monkeypatch.setattr("src.core.tts.EdgeTTSEngine", MockEdge)
    get_provider("edge").synthesize(request, tmp_path / "mock.wav", {}, lambda: False)
    assert calls == [{"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%"}, "中文试听。"]


def test_deleted_starter_take_can_save_new_recipe_from_frozen_history(tmp_path):
    svc = service(tmp_path)
    recipe = svc.active_recipes()[0]
    request = compile_recipe(recipe, build_plan("历史试听。"), {})[0]
    with svc.store._locked():
        state = svc.store._read()
        state["collections"]["takes"]["old-take"] = {
            "id": "old-take", "status": "completed", "recipe_id": recipe["id"],
            "compiled_request": request}
        svc.store._write(state)
    cleanup = SpeechCleanupService(svc, SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: []))
    preview = cleanup.preview("recipes", recipe["id"])
    assert not preview["blockers"]
    cleanup.execute("recipes", recipe["id"], preview["token"], True)
    restarted = service(tmp_path)
    assert restarted.active_recipes() == []
    copied = restarted.save_rule_from_take("old-take", {"name": "从历史试听另存"})
    assert copied["id"] != recipe["id"]
    assert copied["variant"] == recipe["variant"]
    assert restarted.store.get("takes", "old-take")["compiled_request"] == request


def test_missing_dependency_does_not_hide_preset_or_claim_ready(tmp_path, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    svc = service(tmp_path)
    recipe = svc.active_recipes()[0]
    assert get_provider("edge").probe({})["ready"] is False
    with pytest.raises(ValueError, match="未就绪"):
        svc.pipeline_snapshot({"provider": "edge", "model": "edge-tts",
                               "options": {"speech_recipe_id": recipe["id"]}})


def test_http_list_delete_restart_readd_share_ordinary_recipe(tmp_path, monkeypatch):
    monkeypatch.setattr("src.app.services.preset_catalog_service.get_preset_catalog_service", lambda: SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: []))
    svc = service(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_speech_service] = lambda: svc
    with TestClient(app) as client:
        recipe = client.get("/speech/rules").json()["recipes"][0]
        preview = client.post("/speech/cleanup/recipes/" + recipe["id"] + "/preview").json()
        assert client.delete("/speech/rules/" + recipe["id"], params={"token": preview["token"], "confirmed": True}).status_code == 200
        svc = service(tmp_path)
        assert client.get("/speech/rules").json()["recipes"] == []
        response = client.post("/speech/default-preset/add")
        assert response.status_code == 200
        assert response.json()["id"] != recipe["id"]
        assert len(client.get("/speech/rules").json()["recipes"]) == 1
