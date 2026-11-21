"""Stage recovery facts survive restart and never trust partial artifacts."""
from pathlib import Path
import sqlite3

import pytest

from src.app.persistence.recovery_store import RecoveryStore, fingerprint
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


@pytest.mark.parametrize("damage", ["missing", "same_size"])
def test_modified_checkpoint_artifacts_are_not_reusable(stores, tmp_path, damage):
    _, recovery = stores
    output = tmp_path / "audio.wav"
    output.write_bytes(b"original")
    record = recovery.commit("pipeline-1", "tts", "fp", {}, [str(output)])
    stored = Path(record["files"][0]["path"])
    if damage == "missing":
        stored.unlink()
    else:
        stored.write_bytes(b"tampered")
    assert recovery.validated("pipeline-1", "tts", "fp") is None


def test_changed_inputs_configuration_or_schema_invalidate_checkpoint(stores):
    state, recovery = stores
    original = {"input": "abc", "model": "v1", "upstream": "u1"}
    recovery.commit("pipeline-1", "translate", fingerprint(original), {"translations": ["x"]}, [])
    changed = {**original, "input": "changed"}
    assert recovery.validated("pipeline-1", "translate", fingerprint(changed)) is None
    assert recovery.validated("pipeline-1", "asr", fingerprint(original)) is None
    with state._connect() as connection:
        connection.execute("UPDATE stage_checkpoints SET record_json = ?", ('{"version":99}',))
    assert recovery.validated("pipeline-1", "translate", fingerprint(original)) is None


def test_failed_commit_does_not_replace_previous_success(stores, tmp_path):
    _, recovery = stores
    previous = recovery.commit("pipeline-1", "asr", "old", {"segments": []}, [])
    output = tmp_path / "output"
    output.write_bytes(b"complete")
    before = set(recovery.root.iterdir())
    with pytest.raises(TypeError):
        recovery.commit("pipeline-1", "asr", "new", {"bad": object()}, [str(output)])
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
