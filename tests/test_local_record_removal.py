"""Deletion boundary tests using isolated configuration, SQLite and input files."""
from contextlib import nullcontext
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.errors import AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services.settings_service import SettingsService
from src.app.services.batch_run_service import BatchRunService
from src.app.services import llm_connection_removal as removal
from src.core.batches import BatchRunItem, BatchRunRecord
from src.provider_profiles import profiles_for

REFERENCE_LOADER = removal.removal_references


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    module = importlib.import_module("src.config")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = object.__new__(module.Config)
    entries = [{"id": id, "name": id, "provider": "openai", "model": "model",
                "base_url": "https://unit.invalid/v1", "api_key": "same-private-key"}
               for id in ("active", "unused")]
    config.save({"connection_profiles": {"llm": entries, "active_llm": "active"}})
    config.reload()
    references = []
    monkeypatch.setattr(removal, "reference_guard", nullcontext)
    monkeypatch.setattr(removal, "removal_references", lambda _: deepcopy(references))
    return SettingsService(config_manager=config), references


def change(service, id="unused"):
    preview = service.connection_removal_preview(id)
    return service.delete_connection(id, token=preview["token"], confirmed=True)


def test_profile_deletion_restart_and_shared_credentials(profiles):
    service, _ = profiles
    public = change(service)
    assert [p["id"] for p in public["connection_profiles"]["llm"]] == ["active"]
    assert public["connection_profiles"]["removed_llm"] == []
    assert "same-private-key" not in json.dumps(public)
    stored = service.config.get_file_config()["connection_profiles"]["llm"]
    assert len(stored) == 1 and stored[0]["api_key"] == "same-private-key"
    service.config.reload()
    service.update_settings({"paths": {"output_dir": "output-test"}})
    assert [p["id"] for p in profiles_for(service.config.to_dict())["llm"]] == ["active"]
    with pytest.raises(AppValidationError):
        service.connection_removal_preview("unused")


def test_removed_profile_cannot_be_selected_edited_or_resolved_for_new_tasks(profiles):
    from src.task_connection_context import resolve_task_settings
    service, _ = profiles
    change(service)
    before = service.config.get_file_config()
    with pytest.raises(AppValidationError):
        service.update_settings({"active_connections": {"llm": "unused"}})
    with pytest.raises(AppValidationError):
        service.update_settings({"connection_profile": {"kind": "llm", "id": "unused", "name": "renamed"}})
    with pytest.raises(ValueError, match="不存在"):
        resolve_task_settings(service.config.to_dict(), {"stages": {"translate": {
            "provider": "openai", "options": {"connection_ref": "unused"}}}})
    assert service.config.get_file_config() == before


def test_default_and_new_references_block_removal_without_writes(profiles):
    service, references = profiles
    before = service.config.get_file_config()
    with pytest.raises(AppValidationError):
        change(service, "active")
    stale = service.connection_removal_preview("unused")
    references.append({"kind": "workflow", "id": "flow", "name": "saved flow"})
    with pytest.raises(AppValidationError, match="已改变"):
        service.delete_connection("unused", token=stale["token"], confirmed=True)
    assert not service.connection_removal_preview("unused")["can_remove"]
    with pytest.raises(AppValidationError):
        change(service)
    assert service.config.get_file_config() == before


def test_changed_profile_and_failed_save_do_not_remove(profiles, monkeypatch):
    service, _ = profiles
    stale = service.connection_removal_preview("unused")
    service.update_settings({"connection_profile": {"kind": "llm", "id": "active", "name": "renamed active"}})
    with pytest.raises(AppValidationError, match="已改变"):
        service.delete_connection("unused", token=stale["token"], confirmed=True)
    before = service.config.get_file_config()
    monkeypatch.setattr(service.config, "persist_updates", Mock(side_effect=OSError("disk failed")))
    with pytest.raises(Exception, match="保存失败"):
        change(service)
    assert service.config.get_file_config() == before


def test_profile_reference_inventory_includes_archived_workflows_and_active_work(profiles, monkeypatch):
    from src.app.services import preset_catalog_service, task_service, batch_run_service
    # Undo only the fixture's reference-loader replacement for this integration check.
    monkeypatch.setattr(removal, "removal_references", REFERENCE_LOADER)
    profile = {"graph": {"nodes": [{"kind": "translate", "options": {"connection_ref": "unused"}}]}}
    monkeypatch.setattr(preset_catalog_service, "get_preset_catalog_service", lambda: SimpleNamespace(
        list_presets=lambda: [{"id": "saved", "label": "saved", **profile}],
        list_archived_presets=lambda: [{"id": "archived", "label": "archived", **profile}]))
    monkeypatch.setattr(task_service, "_service", SimpleNamespace(history_snapshot=lambda: [
        (SimpleNamespace(task_id="running", execution_profile=profile), SimpleNamespace(state="running")),
        (SimpleNamespace(task_id="done", execution_profile=profile), SimpleNamespace(state="completed")),
        (SimpleNamespace(task_id="pinned-default", execution_profile={}), SimpleNamespace(state="pending"))],
        _connection_records={"pinned-default": {"references": [{"kind": "llm", "id": "unused", "selected": True}]}}))
    monkeypatch.setattr(batch_run_service, "_service", SimpleNamespace(history_snapshot=lambda: [
        SimpleNamespace(batch_id="batch", name="batch", state="pending", execution_profile=profile)]))
    assert {item["id"] for item in removal.removal_references("unused")} == {"saved", "archived", "running", "pinned-default", "batch"}
    assert not removal.references_profile({"stages": []}, "unused")
    assert not removal.references_profile({"graph": {"nodes": [{"kind": "tts", "options": {"connection_ref": "unused"}}]}}, "unused")


@pytest.fixture
def batch(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"untouched input")
    record = BatchRunRecord(batch_id="batch-unit", name="unit", state="cancelled", progress=1,
        created_at="2026-01-01", updated_at="2026-01-01", finished_at="2026-01-01",
        output_dir=str(tmp_path), execution_profile={}, max_parallel=1,
        items=[BatchRunItem(item_id="never-submitted", input_path=str(source), state="cancelled", progress=1)])
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.save_batch_run(record)
    service = BatchRunService(pipeline_orchestrator=Mock(), state_store=store)
    return service, store, source


def set_item(service, expected=None):
    record = service.get_batch("batch-unit")
    return service.delete_unsubmitted_item("batch-unit", "never-submitted",
        expected_updated_at=expected or record.updated_at, confirmed=True)


def test_last_batch_item_deletion_persists_and_never_touches_inputs(batch):
    service, store, source = batch
    assert set_item(service) is None
    assert source.read_bytes() == b"untouched input"
    assert store.load_batch_runs() == []
    restarted = BatchRunService(pipeline_orchestrator=Mock(), state_store=store)
    assert restarted.list_batches() == []
    assert "batch-unit" in restarted._deleted_batches


@pytest.mark.parametrize("field,value", [("state", "pending"), ("current_task_id", "task"), ("task_ids", ["task"])])
def test_batch_item_active_or_bound_is_rejected(batch, field, value):
    service, store, source = batch
    setattr(service._batches["batch-unit"].items[0], field, value)
    before = deepcopy(store.load_batch_runs())
    with pytest.raises(AppValidationError):
        set_item(service)
    assert store.load_batch_runs() == before
    assert source.exists()


def test_batch_active_monitor_stale_confirmation_and_save_failure(batch, monkeypatch):
    service, store, _ = batch
    service._threads["batch-unit"] = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(AppValidationError):
        set_item(service)
    service._threads.clear()
    stale = service.get_batch("batch-unit").updated_at
    service._batches["batch-unit"].updated_at = "changed"
    with pytest.raises(AppValidationError, match="已改变"):
        set_item(service, expected=stale)
    before = deepcopy(service._batches["batch-unit"])
    monkeypatch.setattr(store, "delete_empty_batch", Mock(side_effect=OSError("disk failed")))
    with pytest.raises(OSError):
        set_item(service)
    assert service._batches["batch-unit"] == before


def test_http_removal_contracts_and_strict_confirmation(profiles, batch):
    from src.api.http import dependencies
    from src.api.http.routes import settings, batch_runs
    service, _ = profiles
    batches, _, _ = batch
    app = FastAPI()
    app.include_router(settings.router)
    app.include_router(batch_runs.router)
    app.dependency_overrides[dependencies.settings_service] = lambda: service
    app.dependency_overrides[dependencies.batch_run_service] = lambda: batches
    client = TestClient(app)
    preview = client.get("/settings/connections/unused/removal-preview").json()
    response = client.post("/settings/connections/unused/removal", json={"token": preview["token"], "confirmed": True})
    assert response.status_code == 200
    assert "same-private-key" not in response.text
    assert client.post("/settings/connections/unused/removal", json={"token": preview["token"], "confirmed": "true"}).status_code == 422
    current = batches.get_batch("batch-unit")
    response = client.post("/batch-runs/batch-unit/items/never-submitted/removal",
        json={"expected_updated_at": current.updated_at, "confirmed": True})
    assert response.status_code == 200
    assert response.json()["batch"] is None
    assert client.post("/batch-runs/batch-unit/items/never-submitted/removal",
        json={"expected_updated_at": current.updated_at, "confirmed": 1}).status_code == 422
