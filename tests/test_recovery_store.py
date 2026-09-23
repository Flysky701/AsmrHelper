"""Stage recovery facts survive restart and never trust partial artifacts."""
from pathlib import Path
import sqlite3

import pytest

from src.app.persistence.recovery_store import RecoveryStore, file_identity, fingerprint
from src.app.persistence.state_store import SqliteStateStore
from src.core.tasks import TaskSpec, TaskStatus


def save_task(state, task_id="pipeline-1", task_state="running"):
    spec = TaskSpec(task_id, "pipeline", "test", "session-1", created_at="original")
    status = TaskStatus(task_id, task_state, stage="translate", progress=0.4,
                        task_type="pipeline", created_at="original", updated_at="original")
    state.save_task(spec, status)
    return spec, status


@pytest.fixture
def stores(tmp_path):
    state = SqliteStateStore(tmp_path / "state.sqlite3")
    save_task(state)
    return state, RecoveryStore(state)


def test_manifest_round_trips_after_reopening_database(stores):
    state, recovery = stores
    manifest = {"version": 1, "input": {"path": "audio.wav"},
                "profile": {"source_language": "ja"}, "connection_id": "stable-id"}
    recovery.save_manifest("pipeline-1", manifest)
    manifest["profile"]["source_language"] = "en"
    reopened = RecoveryStore(SqliteStateStore(state.db_path))
    assert reopened.manifest("pipeline-1")["profile"] == {"source_language": "ja"}
    assert reopened.manifest("missing") is None


def test_checkpoint_keeps_immutable_output_and_structured_payload(stores, tmp_path):
    state, recovery = stores
    output = tmp_path / "segments.json"
    output.write_text('[{"start":0,"end":1,"text":"原文"}]', encoding="utf-8")
    payload = {"segments": [{"start": 0, "end": 1, "text": "原文"}]}
    record = recovery.commit("pipeline-1", "asr", "fp", payload, [str(output), str(output)])
    payload["segments"].clear()
    output.write_text("later attempt", encoding="utf-8")
    reopened = RecoveryStore(SqliteStateStore(state.db_path))
    restored = reopened.validated("pipeline-1", "asr", "fp")
    assert len(restored["files"]) == 1
    assert restored["payload"]["segments"][0]["text"] == "原文"
    assert Path(restored["files"][0]["path"]).read_text(encoding="utf-8").startswith("[{")
    assert record["producer_task_id"] == "pipeline-1"
    assert record["completed_at"]
    assert restored["files"][0]["original"] == str(output.resolve())


@pytest.mark.parametrize("damage", ["missing", "same_size", "truncated"])
def test_modified_checkpoint_artifacts_are_not_reusable(stores, tmp_path, damage):
    _, recovery = stores
    output = tmp_path / "audio.wav"
    output.write_bytes(b"original")
    record = recovery.commit("pipeline-1", "tts", "fp", {}, [str(output)])
    stored = Path(record["files"][0]["path"])
    if damage == "missing":
        stored.unlink()
    else:
        stored.write_bytes(b"tampered" if damage == "same_size" else b"x")
    assert recovery.validated("pipeline-1", "tts", "fp") is None


def test_changed_inputs_configuration_or_schema_invalidate_checkpoint(stores):
    state, recovery = stores
    original = {"input": "abc", "model": "v1", "upstream": "u1"}
    recovery.commit("pipeline-1", "translate", fingerprint(original), {"translations": ["x"]}, [])
    for field in original:
        changed = {**original, field: "changed"}
        assert recovery.validated("pipeline-1", "translate", fingerprint(changed)) is None
    assert recovery.validated("pipeline-1", "asr", fingerprint(original)) is None
    with state._connect() as connection:
        connection.execute("UPDATE stage_checkpoints SET record_json = ?", ('{"version":99}',))
    assert recovery.validated("pipeline-1", "translate", fingerprint(original)) is None


@pytest.mark.parametrize("failure", ["empty", "missing", "unserializable"])
def test_failed_commit_does_not_replace_previous_success(stores, tmp_path, failure):
    _, recovery = stores
    previous = recovery.commit("pipeline-1", "asr", "old", {"segments": []}, [])
    output = tmp_path / "output"
    if failure != "missing":
        output.write_bytes(b"" if failure == "empty" else b"complete")
    payload = {"bad": object()} if failure == "unserializable" else {}
    before = set(recovery.root.iterdir())
    with pytest.raises((ValueError, OSError, TypeError)):
        recovery.commit("pipeline-1", "asr", "new", payload, [str(output)])
    assert recovery.checkpoint("pipeline-1", "asr") == previous
    assert set(recovery.root.iterdir()) == before


def test_database_commit_failure_leaves_no_checkpoint_or_output_directory(stores, tmp_path):
    _, recovery = stores
    output = tmp_path / "audio.wav"
    output.write_bytes(b"complete")
    with pytest.raises(sqlite3.IntegrityError):
        recovery.commit("unknown-task", "tts", "fp", {}, [str(output)])
    assert recovery.checkpoint("unknown-task", "tts") is None
    assert list(recovery.root.iterdir()) == []


def test_restart_retains_recoverable_tasks_and_preserves_terminal_history(stores):
    state, recovery = stores
    recovery.save_manifest("pipeline-1", {"version": 1})
    recovery.commit("pipeline-1", "asr", "fp", {"segments": []}, [])
    save_task(state, "pipeline-2", "pending")
    recovery.save_manifest("pipeline-2", {"version": 1})
    save_task(state, "legacy-pending", "pending")
    _, completed = save_task(state, "completed", "completed")
    recovery.save_manifest("completed", {"version": 1})
    reopened_state = SqliteStateStore(state.db_path)
    reopened = RecoveryStore(reopened_state)
    reopened.retain_interrupted()
    assert reopened_state.purge_unfinished() == 1
    statuses = {status.task_id: status for _, status in reopened_state.load_terminal_tasks()}
    for task_id in ("pipeline-1", "pipeline-2"):
        status = statuses[task_id]
        assert status.state == "failed"
        assert status.error["code"] == "TASK_INTERRUPTED"
        assert status.error["retryable"] is True
        assert status.stage == "translate"
        assert status.progress == 0.4
        assert status.created_at == "original"
        assert status.finished_at
    assert statuses["completed"] == completed
    assert reopened.validated("pipeline-1", "asr", "fp") is not None
    reopened.retain_interrupted()
    assert dict((s.task_id, s) for _, s in reopened_state.load_terminal_tasks()) == statuses


def test_file_identity_hashes_content_and_fingerprint_ignores_mapping_order(tmp_path):
    output = tmp_path / "audio"
    output.write_bytes(b"abcdef")
    before = file_identity(output)
    output.write_bytes(b"fedcba")
    after = file_identity(output)
    assert before["size"] == after["size"]
    assert before["sha256"] != after["sha256"]
    assert fingerprint({"a": 1, "b": [2]}) == fingerprint({"b": [2], "a": 1})
