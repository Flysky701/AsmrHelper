"""Real SQLite restart/resume contract, without model or remote API calls."""
from copy import deepcopy
from dataclasses import asdict
import json
import sqlite3

import pytest

from src.app.errors import AppExecutionError, AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services.task_service import TaskService
from src.config import config
from src.provider_profiles import project_profiles


@pytest.fixture
def configured(monkeypatch):
    settings = project_profiles({"api": {}, "connection_profiles": {
        "active_llm": "original-llm", "active_tts": "original-tts",
        "llm": [
            {"id": "original-llm", "name": "Original", "provider": "deepseek",
             "base_url": "https://original.example", "model": "original-model", "api_key": "original-llm-secret"},
            {"id": "other-llm", "name": "Other", "provider": "deepseek",
             "base_url": "https://other.example", "model": "other-model", "api_key": "other-llm-secret"}],
        "tts": [
            {"id": "original-tts", "name": "Original TTS", "provider": "openai_compatible",
             "base_url": "https://user:url-password@tts.example?token=url-token", "api_key": "original-tts-secret",
             "options": {"headers": {"Authorization": "nested-secret"}}},
            {"id": "other-tts", "name": "Other TTS", "provider": "openai_compatible",
             "base_url": "https://other-tts.example", "api_key": "other-tts-secret"}]}})
    monkeypatch.setattr(config, "_config", settings)
    return settings


def _create(service, tmp_path, *, manifest=True):
    spec, _ = service.create_task_spec(
        task_type="pipeline", task_source="test", session_id="old-session",
        input_asset_id="old-audio", companion_asset_ids=["old-subtitle"],
        execution_profile={"source_language": "ja", "target_language": "zh", "translate": True})
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"test-audio")
    subtitle = tmp_path / "source.vtt"
    subtitle.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\ntest\n", encoding="utf-8")
    if manifest:
        service.save_pipeline_manifest(spec.task_id, input_path=str(audio),
                                       companion_paths=[str(subtitle)], output_root=str(tmp_path / "out"))
    return spec


def _resume(service, task_id):
    return service.resume_pipeline_task(task_id, session_id="new-session",
                                        input_asset_id="new-audio", companion_asset_ids=["new-subtitle"])


@pytest.mark.parametrize("started", [False, True])
def test_restart_retains_recoverable_pending_or_running_task_without_auto_execution(configured, tmp_path, started):
    store = SqliteStateStore(tmp_path / "state.db")
    first = TaskService(state_store=store)
    spec = _create(first, tmp_path)
    if started:
        first.start_task(spec.task_id, stage="asr")
        first.update_progress(spec.task_id, 0.25, stage="asr")
    restored = TaskService(state_store=store)
    status = restored.get_task(spec.task_id)
    assert status.state == "failed"
    assert status.error["code"] == "TASK_INTERRUPTED"
    assert status.error["stage"] == ("asr" if started else "prepare")
    assert restored.running_count() == 0
    assert len(restored.list_tasks()) == 1
    assert restored.is_restored_history(spec.task_id)
    assert restored.recovery_info(spec.task_id) == {"can_resume": True, "reason": None, "completed_stages": []}
    # A second restart must preserve the first interruption event/timestamps.
    again = TaskService(state_store=store)
    assert asdict(again.get_task(spec.task_id)) == asdict(status)


def test_explicit_resume_creates_attempt_and_preserves_original_connections_and_history(configured, tmp_path):
    store = SqliteStateStore(tmp_path / "state.db")
    first = TaskService(state_store=store)
    spec = _create(first, tmp_path)
    first.start_task(spec.task_id, stage="translate")
    original_manifest = first.recovery_store.manifest(spec.task_id)
    configured["connection_profiles"].update(active_llm="other-llm", active_tts="other-tts")
    project_profiles(configured)
    restored = TaskService(state_store=store)
    original_status = asdict(restored.get_task(spec.task_id))
    resumed = _resume(restored, spec.task_id)
    new_spec = restored.get_task_spec(resumed.task_id)
    assert resumed.task_id != spec.task_id
    assert resumed.state == "pending"
    assert resumed.retry_of_task_id == spec.task_id
    assert new_spec.retry_of_task_id == spec.task_id
    assert new_spec.session_id == "new-session"
    assert new_spec.input_asset_id == "new-audio"
    assert new_spec.companion_asset_ids == ["new-subtitle"]
    assert new_spec.execution_profile == spec.execution_profile
    assert asdict(restored.get_task(spec.task_id)) == original_status
    assert restored.recovery_store.manifest(spec.task_id) == original_manifest
    assert restored.recovery_store.manifest(resumed.task_id)["resume_of_task_id"] == spec.task_id
    with restored.connection_context(resumed.task_id):
        assert config.get("api.deepseek_api_key") == "original-llm-secret"
        assert config.get("api.deepseek_model") == "original-model"
        assert config.get("external_tts.api_key") == "original-tts-secret"
    assert config.get("api.deepseek_api_key") == "other-llm-secret"
    with pytest.raises(AppValidationError, match="已有"):
        _resume(restored, spec.task_id)
    assert not restored.recovery_info(spec.task_id)["can_resume"]
    # Continuing is explicit: even creating the attempt does not execute it.
    assert restored.running_count() == 0
    assert len(restored.list_tasks()) == 2


def test_history_without_manifest_cannot_resume(configured, tmp_path):
    store = SqliteStateStore(tmp_path / "state.db")
    service = TaskService(state_store=store)
    spec = _create(service, tmp_path, manifest=False)
    service.start_task(spec.task_id)
    service.fail_task(spec.task_id, "failure")
    restored = TaskService(state_store=store)
    assert not restored.recovery_info(spec.task_id)["can_resume"]
    with pytest.raises(AppValidationError, match="执行清单"):
        _resume(restored, spec.task_id)


@pytest.mark.parametrize("change", ["credential", "deleted_profile", "missing_input"])
def test_resume_blocks_missing_input_or_changed_original_connection(configured, tmp_path, change):
    store = SqliteStateStore(tmp_path / "state.db")
    service = TaskService(state_store=store)
    spec = _create(service, tmp_path)
    service.start_task(spec.task_id)
    if change == "credential":
        configured["connection_profiles"]["llm"][0]["api_key"] = "rotated-secret"
    elif change == "deleted_profile":
        configured["connection_profiles"]["llm"].pop(0)
        configured["connection_profiles"]["active_llm"] = "other-llm"
        project_profiles(configured)
    else:
        (tmp_path / "source.wav").unlink()
    restored = TaskService(state_store=store)
    info = restored.recovery_info(spec.task_id)
    assert not info["can_resume"]
    with pytest.raises(AppValidationError):
        _resume(restored, spec.task_id)
    assert len(restored.list_tasks()) == 1


def test_secrets_never_enter_manifest_or_sqlite_dump(configured, tmp_path):
    store = SqliteStateStore(tmp_path / "state.db")
    service = TaskService(state_store=store)
    spec = _create(service, tmp_path)
    service.start_task(spec.task_id)
    restored = TaskService(state_store=store)
    _resume(restored, spec.task_id)
    manifest_json = json.dumps(restored.recovery_store.manifest(spec.task_id))
    with sqlite3.connect(store.db_path) as connection:
        dump = "\n".join(connection.iterdump())
    for secret in ("original-llm-secret", "other-llm-secret", "original-tts-secret",
                   "other-tts-secret", "url-password", "url-token", "nested-secret"):
        assert secret not in manifest_json
        assert secret not in dump


def test_manifest_persistence_failure_does_not_leave_orphan_resume_attempt(configured, tmp_path):
    store = SqliteStateStore(tmp_path / "state.db")
    service = TaskService(state_store=store)
    spec = _create(service, tmp_path)
    service.start_task(spec.task_id)
    restored = TaskService(state_store=store)
    original = deepcopy(asdict(restored.get_task(spec.task_id)))

    with sqlite3.connect(store.db_path) as connection:
        connection.execute("CREATE TRIGGER reject_manifest BEFORE INSERT ON recovery_manifests "
                           "BEGIN SELECT RAISE(FAIL, 'injected write failure'); END")
    with pytest.raises(AppExecutionError, match="persist"):
        _resume(restored, spec.task_id)
    assert len(restored.list_tasks()) == 1
    assert asdict(restored.get_task(spec.task_id)) == original
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT task_id FROM tasks").fetchall() == [(spec.task_id,)]
