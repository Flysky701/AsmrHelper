"""All fixtures live under tmp_path; never inspect/delete user voice data."""
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest

from src.app.services.speech_cleanup_service import SpeechCleanupService, owned_path
from src.core.speech.store import SpeechStore, _hash_file
from src.core.tasks.models import TaskSpec, TaskStatus


@pytest.fixture
def cleanup(tmp_path):
    store = SpeechStore(tmp_path / "voice_lab")
    tasks = SimpleNamespace(history_deletion_guard=nullcontext, history_snapshot=lambda: [], _state_store=None)
    artifacts = SimpleNamespace(history_deletion_guard=nullcontext, list_records=lambda: [])
    dispatcher = SimpleNamespace(history_deletion_guard=nullcontext, has_live_worker=lambda _: False)
    speech = SimpleNamespace(store=store, tasks=tasks, artifacts=artifacts, dispatcher=dispatcher)
    catalog = SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: [])
    return SpeechCleanupService(speech, catalog)


def seed(cleanup, **collections):
    state = cleanup.store._read()
    for key, rows in collections.items():
        state["collections"][key].update({row["id"]: row for row in rows})
    cleanup.store._write(state)


def experiment(cleanup):
    path = cleanup.store.root / "takes" / "take.wav"
    path.parent.mkdir()
    path.write_bytes(b"fixture audio")
    seed(cleanup, experiments=[{"id": "experiment", "plan_id": "plan"}],
         plans=[{"id": "plan", "text": "test"}],
         takes=[{"id": "take", "experiment_id": "experiment", "audio_path": str(path), "plan_id": "plan"}],
         selections=[{"id": "selection", "experiment_id": "experiment", "take_id": "take"}])
    return path


def staged(cleanup):
    id = str(uuid4())
    path = cleanup.store.root / "_staging" / id / "source.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fixture source")
    row = {"id": id, "path": str(path), "source_path": str(path), "sha256": _hash_file(path), "source_sha256": _hash_file(path)}
    (path.parent / "inspection.json").write_text(json.dumps(row), encoding="utf-8")
    return path, id


def test_experiment_cleanup_and_restore_survive_new_service(cleanup):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    assert preview["blockers"] == []
    assert preview["records"] == {"experiments": 1, "takes": 1, "plans": 1, "selections": 1}
    receipt = cleanup.execute("experiments", "experiment", preview["token"], True)
    assert not path.exists()
    assert cleanup.store.list("experiments") == []
    reopened = SpeechCleanupService(cleanup.speech, cleanup.catalog)
    assert reopened.receipts()[0]["id"] == receipt["id"]
    reopened.restore(receipt["id"])
    assert path.read_bytes() == b"fixture audio"
    assert cleanup.store.get("takes", "take")["experiment_id"] == "experiment"
    assert reopened.receipts() == []


def test_confirmation_and_stale_preview(cleanup):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    with pytest.raises(ValueError, match="确认"):
        cleanup.execute("experiments", "experiment", preview["token"])
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="改变"):
        cleanup.execute("experiments", "experiment", preview["token"], True)
    assert path.exists()


@pytest.mark.parametrize("source", ["voices", "future_collection", "history", "artifact", "preset", "recovery"])
def test_any_known_or_unknown_reference_blocks(cleanup, source):
    path = experiment(cleanup)
    if source == "history":
        cleanup.speech.tasks.history_snapshot = lambda: [(TaskSpec("task", "speech.generate", "test", "experiment"), TaskStatus("task", "completed"))]
    elif source == "artifact":
        cleanup.speech.artifacts.list_records = lambda: [{"path": str(path)}]
    elif source == "preset":
        cleanup.catalog.list_presets = lambda: [{"some_future_ref": "take"}]
    elif source == "recovery":
        cleanup.speech.tasks._state_store = SimpleNamespace(deletion_inventory=lambda: {"manifests": [{"snapshot": "take"}]})
    else:
        state = cleanup.store._read()
        state["collections"].setdefault(source, {})["saved"] = {"unknown": "take"}
        cleanup.store._write(state)
    preview = cleanup.preview("experiments", "experiment")
    assert preview["blockers"]
    with pytest.raises(ValueError):
        cleanup.execute("experiments", "experiment", preview["token"], True)
    assert path.exists()


def test_running_and_exiting_worker_block(cleanup):
    experiment(cleanup)
    spec, status = TaskSpec("task", "test", "test", ""), TaskStatus("task", "running")
    cleanup.speech.tasks.history_snapshot = lambda: [(spec, status)]
    assert cleanup.preview("experiments", "experiment")["blockers"]
    status.state = "cancelled"
    cleanup.speech.dispatcher.has_live_worker = lambda _: True
    assert cleanup.preview("experiments", "experiment")["blockers"]


def test_formal_and_outside_paths_retained(cleanup, tmp_path):
    path = experiment(cleanup)
    state = cleanup.store._read()
    state["collections"]["experiments"]["experiment"]["kind"] = "formal"
    cleanup.store._write(state)
    assert cleanup.preview("experiments", "experiment")["blockers"]
    outside = tmp_path / "user.wav"
    outside.write_bytes(b"user")
    state["collections"]["takes"]["take"]["audio_path"] = str(outside)
    cleanup.store._write(state)
    with pytest.raises(ValueError):
        cleanup.preview("experiments", "experiment")
    assert outside.read_bytes() == b"user" and path.exists()


def test_staging_retains_referenced_and_unknown_entries(cleanup):
    free, _ = staged(cleanup)
    used, id = staged(cleanup)
    seed(cleanup, assets=[{"id": "saved", "inspection_id": id}])
    unknown = free.parent.parent / "unknown"
    unknown.mkdir()
    (unknown / "user.wav").write_bytes(b"keep")
    preview = cleanup.preview("staging")
    assert preview["paths"] == [str(free.parent)]
    receipt = cleanup.execute("staging", "all", preview["token"], True)
    assert not free.exists() and used.exists() and unknown.exists()
    cleanup.restore(receipt["id"])
    assert free.exists()


def test_archived_assets_preserve_original_and_restore(cleanup, tmp_path):
    original = tmp_path / "user.wav"
    original.write_bytes(b"user")
    directory = cleanup.store.assets_root / str(uuid4())
    directory.mkdir(parents=True)
    path = directory / "reference.wav"
    path.write_bytes(b"owned")
    seed(cleanup, assets=[{"id": "asset", "archived": True, "path": str(path), "source_path": str(path), "original_path": str(original)}])
    preview = cleanup.preview("assets", "asset")
    receipt = cleanup.execute("assets", "asset", preview["token"], True)
    assert not path.exists() and original.read_bytes() == b"user"
    cleanup.restore(receipt["id"])
    assert path.read_bytes() == b"owned"


def test_archived_rule_chain_retains_history_references(cleanup):
    seed(cleanup, recipes=[{"id": "r1"}, {"id": "r2", "previous_id": "r1"}], rule_states=[{"id": "r1", "archived": True}])
    seed(cleanup, takes=[{"id": "historical", "recipe_id": "r1"}])
    assert cleanup.preview("recipes", "r2")["blockers"]


def test_write_failure_rolls_back_files(cleanup, monkeypatch):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    monkeypatch.setattr(cleanup.store, "_write", lambda _: (_ for _ in ()).throw(OSError("fixture failure")))
    with pytest.raises(OSError):
        cleanup.execute("experiments", "experiment", preview["token"], True)
    assert path.exists()
    assert cleanup.store.get("experiments", "experiment")


def test_restore_does_not_overwrite_or_accept_changed_trash(cleanup):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    receipt = cleanup.execute("experiments", "experiment", preview["token"], True)
    path.write_bytes(b"new user file")
    with pytest.raises(ValueError, match="已有"):
        cleanup.restore(receipt["id"])
    assert path.read_bytes() == b"new user file"
    path.unlink()
    (cleanup.store.root / "_trash" / receipt["id"] / "0").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="改变"):
        cleanup.restore(receipt["id"])


def test_paths_reject_traversal_and_links(cleanup, tmp_path):
    with pytest.raises(ValueError):
        owned_path(cleanup.store.root, tmp_path / "outside")
    target = tmp_path / "target"
    target.mkdir()
    link = cleanup.store.root / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        owned_path(cleanup.store.root, link / "anything")


def test_explicit_purge_releases_only_quarantined_files(cleanup):
    path = experiment(cleanup)
    first = cleanup.preview("experiments", "experiment")
    receipt = cleanup.execute("experiments", "experiment", first["token"], True)
    preview = cleanup.preview("trash", receipt["id"])
    assert not preview["recoverable"] and preview["bytes"] > 0
    with pytest.raises(ValueError, match="确认"):
        cleanup.execute("trash", receipt["id"], preview["token"])
    cleanup.execute("trash", receipt["id"], preview["token"], True)
    assert not path.exists() and cleanup.receipts() == []
    assert not (cleanup.store.root / "_trash" / receipt["id"]).exists()


def test_purge_rechecks_new_references(cleanup):
    experiment(cleanup)
    first = cleanup.preview("experiments", "experiment")
    receipt = cleanup.execute("experiments", "experiment", first["token"], True)
    preview = cleanup.preview("trash", receipt["id"])
    seed(cleanup, voices=[{"id": "saved", "historic_take": "take"}])
    with pytest.raises(ValueError, match="改变"):
        cleanup.execute("trash", receipt["id"], preview["token"], True)
    assert cleanup.preview("trash", receipt["id"])["blockers"]


def test_recoverable_records_keep_dependencies_protected(cleanup):
    experiment(cleanup)
    seed(cleanup, recipes=[{"id": "recipe"}], rule_states=[{"id": "recipe", "archived": True}])
    state = cleanup.store._read()
    state["collections"]["takes"]["take"]["recipe_id"] = "recipe"
    cleanup.store._write(state)
    preview = cleanup.preview("experiments", "experiment")
    receipt = cleanup.execute("experiments", "experiment", preview["token"], True)
    assert cleanup.preview("recipes", "recipe")["blockers"]
    purge = cleanup.preview("trash", receipt["id"])
    cleanup.execute("trash", receipt["id"], purge["token"], True)
    assert not cleanup.preview("recipes", "recipe")["blockers"]


def test_interrupted_move_before_commit_is_recovered(cleanup):
    path = experiment(cleanup)
    _, payload = cleanup._preview("experiments", "experiment")
    receipt_id = uuid4().hex
    trash = cleanup.store.root / "_trash" / receipt_id
    trash.mkdir(parents=True)
    manifest = {**payload, "id": receipt_id, "state": "prepared"}
    (trash / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    path.rename(trash / "0")  # Simulate process exit before store commit.
    assert cleanup.receipts() == []
    assert path.read_bytes() == b"fixture audio"
    assert cleanup.store.get("takes", "take")


def test_junction_component_is_rejected_even_when_target_is_inside_root(cleanup, monkeypatch):
    from pathlib import Path
    target = cleanup.store.root / "junction"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == target, raising=False)
    with pytest.raises(ValueError, match="联接"):
        owned_path(cleanup.store.root, target / "file.wav")


def test_batch_before_child_task_submission_blocks_cleanup(cleanup):
    experiment(cleanup)
    cleanup.batches = SimpleNamespace(history_deletion_guard=nullcontext,
        history_snapshot=lambda: [SimpleNamespace(state="pending")], _graph_snapshots={})
    assert any("批任务" in reason for reason in cleanup.preview("experiments", "experiment")["blockers"])


def test_completed_batch_frozen_reference_stays_protected(cleanup):
    experiment(cleanup)
    cleanup.batches = SimpleNamespace(history_deletion_guard=nullcontext,
        history_snapshot=lambda: [SimpleNamespace(state="completed")], _graph_snapshots={"batch": {"take": "take"}})
    assert cleanup.preview("experiments", "experiment")["blockers"]
