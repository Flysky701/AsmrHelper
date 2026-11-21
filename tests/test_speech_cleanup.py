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


@pytest.mark.parametrize("source", [
    "voices",
    "future_collection",
    "history",
    "recovery",
])
def test_any_known_or_unknown_reference_blocks(cleanup, source):
    path = experiment(cleanup)
    if source == "history":
        cleanup.speech.tasks.history_snapshot = lambda: [(TaskSpec("task", "speech.generate", "test", "experiment"), TaskStatus("task", "completed"))]
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
    assert receipt == {"deleted": "asset", "kind": "assets", "recoverable": False,
                       "files_deleted": len(preview["files"]), "bytes_deleted": preview["bytes"]}
    assert not path.exists() and original.read_bytes() == b"user"
    assert cleanup.store.list("assets") == []
    assert not (cleanup.store.root / "_trash").exists()


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


def legacy_fixture(cleanup):
    path = experiment(cleanup)
    _, payload = cleanup._preview("experiments", "experiment")
    id = uuid4().hex
    trash = cleanup.store.root / "_trash" / id
    trash.mkdir(parents=True)
    (trash / "manifest.json").write_text(json.dumps({**payload, "id": id, "state": "committed"}), encoding="utf-8")
    path.rename(trash / "0")
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


def test_batch_before_child_task_submission_blocks_cleanup(cleanup):
    experiment(cleanup)
    cleanup.batches = SimpleNamespace(history_deletion_guard=nullcontext,
        history_snapshot=lambda: [SimpleNamespace(state="pending")], _graph_snapshots={})
    assert any("批任务" in reason for reason in cleanup.preview("experiments", "experiment")["blockers"])


def completed_connection_replacement(cleanup):
    """Produce an actual store receipt entirely inside the temporary fixture."""
    audio = experiment(cleanup)
    recipe = {"id": "recipe", "name": "Fixture", "revision": 1, "voice_id": "voice",
              "provider_id": "qwen3", "model": "qwen3-base", "mode": "reference",
              "connection_ref": "old", "variant": {"kind": "reference", "value": "asset"},
              "provider_options": {"schema_version": 1}}
    request = {key: recipe[key] for key in ("provider_id", "model", "mode")}
    request["recipe_id"] = recipe["id"]
    seed(cleanup, recipes=[recipe], voices=[{"id": "voice"}],
         connections=[{"id": "old", "provider_id": "qwen3"}, {"id": "replacement", "provider_id": "qwen3"}],
         rule_states=[{"id": "recipe", "archived": True}],
         takes=[{**cleanup.store.get("takes", "take"), "recipe_id": "recipe", "compiled_request": request}])
    token = cleanup.store._connection_signature(cleanup.store._read())
    receipt = cleanup.store.prepare_connection_deletion("old", token, "replace", "replacement",
        request_token="review-token", catalog_token="catalog-token", recipe_ids=["recipe"])
    cleanup.store.finalize_connection_deletion(receipt)
    return audio, recipe, cleanup.store.connection_deletion_receipt("review-token")


def test_completed_connection_receipt_survives_rule_deletion_and_replays_without_lookup(cleanup, monkeypatch):
    from src.app.services.speech_connection_service import SpeechConnectionService
    audio, recipe, receipt = completed_connection_replacement(cleanup)
    before = cleanup.store.path.read_bytes()
    preview = cleanup.preview("recipes", "recipe")
    assert preview["blockers"] == [] and preview["files"] == []
    assert preview["records"] == {"voices": 1, "recipes": 2, "rule_states": 1}
    assert cleanup.store.path.read_bytes() == before
    cleanup.execute("recipes", "recipe", preview["token"], True)
    reopened = SpeechStore(cleanup.store.root)
    assert reopened.list("recipes") == [] and reopened.list("voices") == []
    assert reopened.get("takes", "take")["recipe_snapshot"] == recipe
    assert reopened.connection_deletion_receipt("review-token") == receipt
    assert audio.read_bytes() == b"fixture audio"
    assert reopened.get("connections", "replacement")["id"] == "replacement"
    def forbidden(*args, **kwargs):
        pytest.fail("Completed replay must not look up rules, migrate workflows or write")
    monkeypatch.setattr(reopened, "get", forbidden)
    monkeypatch.setattr(reopened, "_write", forbidden)
    monkeypatch.setattr(reopened, "connection_deletion_preview", forbidden)
    service = SpeechConnectionService(SimpleNamespace(store=reopened), SimpleNamespace(speech_connection_references=forbidden))
    assert service.execute("old", token="review-token", action="replace", replacement_ref="replacement") == {
        **receipt["result"], "updated_presets": []}
    assert reopened.finalize_connection_deletion(receipt) == receipt["result"]
