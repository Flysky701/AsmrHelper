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


def test_experiment_deletion_survives_restart_without_recovery_copies(cleanup):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    assert preview["blockers"] == []
    result = cleanup.execute("experiments", "experiment", preview["token"], True)
    assert result["recoverable"] is False
    assert not path.exists()
    reopened = SpeechStore(cleanup.store.root)
    for collection in ("experiments", "takes", "plans", "selections"):
        assert reopened.list(collection) == []
    assert not (cleanup.store.root / "_trash").exists()


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
    assert not free.parent.exists()
    assert not (cleanup.store.root / "_trash").exists()


def test_assets_delete_owned_files_and_preserve_original(cleanup, tmp_path):
    original = tmp_path / "user.wav"
    original.write_bytes(b"user")
    directory = cleanup.store.assets_root / str(uuid4())
    directory.mkdir(parents=True)
    path = directory / "reference.wav"
    path.write_bytes(b"owned")
    seed(cleanup, assets=[{"id": "asset", "path": str(path), "source_path": str(path), "original_path": str(original)}])
    preview = cleanup.preview("assets", "asset")
    receipt = cleanup.execute("assets", "asset", preview["token"], True)
    assert not path.exists() and original.read_bytes() == b"user"
    assert cleanup.store.list("assets") == []
    assert not (cleanup.store.root / "_trash").exists()


def test_archived_rule_chain_retains_history_references(cleanup):
    seed(cleanup, recipes=[{"id": "r1"}, {"id": "r2", "previous_id": "r1"}], rule_states=[{"id": "r1", "archived": True}])
    seed(cleanup, takes=[{"id": "historical", "recipe_id": "r1"}])
    assert cleanup.preview("recipes", "r2")["blockers"]


def test_write_failure_leaves_record_for_explicit_retry(cleanup, monkeypatch):
    path = experiment(cleanup)
    preview = cleanup.preview("experiments", "experiment")
    write = cleanup.store._write
    monkeypatch.setattr(cleanup.store, "_write", lambda _: (_ for _ in ()).throw(OSError("fixture failure")))
    with pytest.raises(ValueError, match="记录保存失败"):
        cleanup.execute("experiments", "experiment", preview["token"], True)
    assert not path.exists()
    assert cleanup.store.get("experiments", "experiment")
    monkeypatch.setattr(cleanup.store, "_write", write)
    preview = cleanup.preview("experiments", "experiment")
    cleanup.execute("experiments", "experiment", preview["token"], True)
    assert cleanup.store.list("experiments") == []


def test_unreviewed_files_are_not_deleted(cleanup):
    path, _ = staged(cleanup)
    preview = cleanup.preview("staging")
    extra = path.parent / "new.wav"
    extra.write_bytes(b"new")
    with pytest.raises(ValueError, match="改变"):
        cleanup.execute("staging", "all", preview["token"], True)
    assert extra.exists() and path.exists()


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


def legacy_fixture(cleanup, prepared=False):
    path = experiment(cleanup)
    _, payload = cleanup._preview("experiments", "experiment")
    id = uuid4().hex
    trash = cleanup.store.root / "_trash" / id
    trash.mkdir(parents=True)
    (trash / "manifest.json").write_text(json.dumps({**payload, "id": id, "state": "prepared" if prepared else "committed"}), encoding="utf-8")
    path.rename(trash / "0")
    if not prepared:
        state = cleanup.store._read()
        for key, rows in payload["records"].items():
            for row in rows:
                state["collections"][key].pop(row)
        state["cleanup_receipts"] = [id]
        cleanup.store._write(state)
    return id, path, trash


def test_legacy_data_is_read_only_until_explicit_confirmed_delete(cleanup):
    id, path, trash = legacy_fixture(cleanup)
    before = (trash / "manifest.json").read_bytes()
    assert cleanup.legacy_records()[0]["id"] == id
    assert (trash / "manifest.json").read_bytes() == before and not path.exists()
    preview = cleanup.preview("legacy-trash", id)
    with pytest.raises(ValueError, match="确认"):
        cleanup.execute("legacy-trash", id, preview["token"])
    cleanup.execute("legacy-trash", id, preview["token"], True)
    assert not trash.exists() and cleanup.legacy_records() == []


def test_legacy_delete_rechecks_references(cleanup):
    id, path, trash = legacy_fixture(cleanup)
    preview = cleanup.preview("legacy-trash", id)
    seed(cleanup, voices=[{"id": "saved", "historic_take": "take"}])
    with pytest.raises(ValueError, match="改变"):
        cleanup.execute("legacy-trash", id, preview["token"], True)
    assert cleanup.preview("legacy-trash", id)["blockers"] and trash.exists()


def test_legacy_prepared_data_is_not_automatically_moved_or_purged(cleanup):
    id, path, trash = legacy_fixture(cleanup, prepared=True)
    assert cleanup.legacy_records()[0]["id"] == id
    assert not path.exists() and (trash / "0").exists()
    assert cleanup.preview("legacy-trash", id)["blockers"]


def test_recipe_delete_freezes_history_and_does_not_reseed_default(cleanup):
    recipe = {"id": "recipe", "voice_id": "voice", "provider_id": "edge", "model": "edge-tts", "mode": "hosted", "variant": {"value": "speaker"}}
    seed(cleanup, recipes=[recipe], voices=[{"id": "voice"}], takes=[{"id": "take", "recipe_id": "recipe"}])
    state = cleanup.store._read()
    state["builtin_recipes"] = {"starter": {"recipe_id": "recipe"}}
    cleanup.store._write(state)
    preview = cleanup.preview("recipes", "recipe")
    assert not preview["blockers"]
    cleanup.execute("recipes", "recipe", preview["token"], True)
    reopened = SpeechStore(cleanup.store.root)
    assert reopened.get("takes", "take")["recipe_snapshot"] == recipe
    assert reopened.list("recipes") == [] and reopened.list("voices") == []
    assert reopened._read()["builtin_recipes"]["starter"]["recipe_id"] == "recipe"


@pytest.mark.parametrize("with_snapshot", [False, True])
def test_compiler_provenance_does_not_block_independent_take(cleanup, with_snapshot):
    recipe = {"id": "recipe", "voice_id": "voice", "provider_id": "edge", "model": "edge-tts",
              "mode": "builtin", "variant": {"kind": "builtin", "value": "zh-CN-XiaoxiaoNeural"}}
    request = {"recipe_id": "recipe", "provider_id": "edge", "model": "edge-tts", "mode": "builtin"}
    take = {"id": "take", "recipe_id": "recipe", "compiled_request": request}
    if with_snapshot:
        take["recipe_snapshot"] = recipe
    seed(cleanup, recipes=[recipe], takes=[take], voices=[{"id": "voice"}])
    before = cleanup.store.path.read_bytes()
    preview = cleanup.preview("recipes", "recipe")
    assert not preview["blockers"]
    assert cleanup.store.path.read_bytes() == before  # Preview never migrates data.
    with pytest.raises(ValueError, match="确认"):
        cleanup.execute("recipes", "recipe", preview["token"], False)
    assert cleanup.store.path.read_bytes() == before
    cleanup.execute("recipes", "recipe", preview["token"], True)
    saved = SpeechStore(cleanup.store.root).get("takes", "take")
    assert saved["recipe_snapshot"] == recipe
    assert saved["compiled_request"] == request  # Preserve provenance in storage.


@pytest.mark.parametrize("problem", ["mismatched_request", "mismatched_snapshot", "unknown_reference"])
def test_frozen_take_still_protects_unresolved_dependencies(cleanup, problem):
    recipe = {"id": "recipe", "provider_id": "edge", "model": "edge-tts", "mode": "builtin", "variant": {}}
    take = {"id": "take", "recipe_id": "recipe", "recipe_snapshot": recipe,
            "compiled_request": {"recipe_id": "recipe", "provider_id": "edge", "model": "edge-tts", "mode": "builtin"}}
    if problem == "mismatched_request":
        take["compiled_request"]["model"] = "unknown"
    elif problem == "mismatched_snapshot":
        take["recipe_snapshot"] = {**recipe, "id": "different"}
    else:
        take["future_dependency"] = {"recipe_id": "recipe"}
    seed(cleanup, recipes=[recipe], takes=[take])
    assert cleanup.preview("recipes", "recipe")["blockers"]


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
