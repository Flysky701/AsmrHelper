"""Weight deletion ownership tests use only fresh temporary directories."""
from contextlib import nullcontext
import json
import threading
from types import SimpleNamespace

import pytest

from src.core.resources.model_removal import MARKER, managed_path, removal_evidence, track_owned_install
from src.app.services.model_removal_service import ModelRemovalService
from src.core.speech.store import SpeechStore
from src.core.tasks.models import TaskSpec, TaskStatus


def entry_for(root, name="fixture"):
    path = root / name
    return SimpleNamespace(id=name, kind="local", supports_remove=True, category="tts", provider="fixture", engine=None,
        capability_models=[], upstream_name=None, required_assets=[], recommended_assets=[],
        resolved_install_root=lambda: root, managed_install_dir=lambda: path, resolved_install_dir=lambda: path)


def create_owned(entry):
    class Installer:
        @track_owned_install
        def install(self, entry):
            path = entry.managed_install_dir()
            path.mkdir(parents=True, exist_ok=True)
            (path / "weight.bin").write_bytes(b"fixture weight")
            return True
    Installer().install(entry)


@pytest.fixture
def removal(tmp_path):
    entry = entry_for(tmp_path / "models")
    create_owned(entry)
    tasks = SimpleNamespace(history_snapshot=lambda: [], history_deletion_guard=nullcontext, _state_store=None)
    speech = SimpleNamespace(store=SpeechStore(tmp_path / "voice"), tasks=tasks,
        dispatcher=SimpleNamespace(history_deletion_guard=nullcontext, has_live_worker=lambda _: False))
    core = SimpleNamespace(get_model=lambda _: entry, list_models=lambda **_: [entry], _install_lock=threading.RLock())
    def remove(_):
        import shutil
        path, _ = removal_evidence(entry)
        shutil.rmtree(path)
    core.remove = remove
    models = SimpleNamespace(core_service=core, _run_model_operation=lambda **kw: kw["runner"]())
    catalog = SimpleNamespace(list_presets=lambda: [], list_archived_presets=lambda: [])
    return ModelRemovalService(models, speech, catalog, lambda: {}), entry


def test_only_new_installs_gain_ownership(tmp_path):
    owned = entry_for(tmp_path / "models")
    create_owned(owned)
    assert removal_evidence(owned)[0] == owned.managed_install_dir()
    old = entry_for(tmp_path / "models", "old")
    old.managed_install_dir().mkdir()
    (old.managed_install_dir() / "user.txt").write_text("user")
    create_owned(old)
    assert not (old.managed_install_dir() / MARKER).exists()
    with pytest.raises(ValueError, match="所有权"):
        removal_evidence(old)


def test_unknown_files_never_adopted_or_removed(removal):
    service, entry = removal
    (entry.managed_install_dir() / "user.txt").write_text("user")
    create_owned(entry)
    assert service.preview(entry.id)["blockers"]
    assert "user.txt" not in json.loads((entry.managed_install_dir() / MARKER).read_text())["files"]


def test_external_and_root_paths_rejected(tmp_path):
    entry = entry_for(tmp_path / "models")
    entry.resolved_install_dir = lambda: tmp_path / "external"
    with pytest.raises(ValueError):
        managed_path(entry)
    entry.resolved_install_dir = lambda: tmp_path / "models"
    entry.managed_install_dir = entry.resolved_install_dir
    with pytest.raises(ValueError):
        managed_path(entry)


def test_confirmed_delete_requires_current_preview(removal):
    service, entry = removal
    preview = service.preview(entry.id)
    assert preview["blockers"] == []
    with pytest.raises(ValueError, match="确认"):
        service.execute(entry.id, preview["token"])
    service.execute(entry.id, preview["token"], True)
    assert not entry.managed_install_dir().exists()


@pytest.mark.parametrize("reference", ["voice", "history", "settings", "workflow", "running", "exiting", "recovery"])
def test_model_references_and_running_workers_block(removal, reference):
    service, entry = removal
    if reference == "voice":
        state = service.speech.store._read()
        state["collections"]["recipes"]["voice"] = {"model": entry.id}
        service.speech.store._write(state)
    elif reference in {"history", "running", "exiting"}:
        profile = {"model": entry.id} if reference == "history" else {}
        service.speech.tasks.history_snapshot = lambda: [(TaskSpec("task", "fixture", "fixture", "", execution_profile=profile), TaskStatus("task", "running" if reference == "running" else "completed"))]
        service.speech.dispatcher.has_live_worker = lambda _: reference == "exiting"
    elif reference == "settings":
        service.settings = lambda: {"model": entry.id}
    elif reference == "workflow":
        service.catalog.list_presets = lambda: [{"model_path": str(entry.managed_install_dir())}]
    else:
        service.speech.tasks._state_store = SimpleNamespace(deletion_inventory=lambda: {"manifests": [{"model": entry.id}]})
    preview = service.preview(entry.id)
    assert preview["blockers"]
    with pytest.raises(ValueError):
        service.execute(entry.id, preview["token"], True)
    assert (entry.managed_install_dir() / "weight.bin").exists()


def test_file_changes_after_preview_block(removal):
    service, entry = removal
    preview = service.preview(entry.id)
    (entry.managed_install_dir() / "weight.bin").write_bytes(b"changed fixture weight")
    with pytest.raises(ValueError, match="改变"):
        service.execute(entry.id, preview["token"], True)


def test_overlapping_model_directory_blocks(removal):
    service, entry = removal
    other = entry_for(entry.resolved_install_root(), "other")
    other.resolved_install_dir = lambda: entry.managed_install_dir() / "nested"
    service.models.core_service.list_models = lambda **_: [entry, other]
    assert any("重叠" in reason for reason in service.preview(entry.id)["blockers"])
