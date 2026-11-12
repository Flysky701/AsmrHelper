"""Exercise Anime Whisper through existing model operations without downloads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.app.services.model_service import ModelService as AppModelService
from src.core.resources import model_assets as assets
from src.core.resources.model_catalog import ModelCatalog, ModelEntry
from src.core.resources.model_installer import ModelInstaller
from src.core.resources.model_removal import MARKER, removal_evidence
from src.core.resources.model_service import ModelService
from src.core.runtime.profiles import RuntimeProfileResolver


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(assets, "sources", list)
    monkeypatch.setattr(ModelEntry, "resolved_install_root", lambda _: tmp_path / "models")
    entry = ModelCatalog().get("anime-whisper")
    return entry


def put_weights(entry, path):
    path.mkdir(parents=True)
    for name in entry.required_files:
        (path / name).write_bytes(b"mock asset, not real weights")


def test_anime_download_progress_verify_skip_and_owned_removal(model, tmp_path, monkeypatch):
    core = ModelService(runtime_resolver=RuntimeProfileResolver(tmp_path))
    downloads = []

    def download(cmd, env, timeout, progress, **kwargs):
        downloads.append(cmd)
        assert "repo_id='litagin/anime-whisper'" in cmd[-1]
        assert str(model.managed_install_dir()) in cmd[-1]
        assert env["HF_ENDPOINT"] == "https://hf-mirror.example"
        assert timeout == 3600
        put_weights(model, model.managed_install_dir())
        progress(0.5, "mock download")
        return True

    monkeypatch.setattr(core.installer, "_run_with_progress", download)
    monkeypatch.setattr(
        core, "_install_runtime_packages", lambda _: pytest.fail("weight-only action")
    )
    progress = []
    assert core.install(
        model.id,
        mirror="https://hf-mirror.example",
        install_dependencies=False,
        on_progress=lambda fraction, message: progress.append((fraction, message)),
    )
    assert progress[-1] == (1.0, "download complete")
    assert core.verify(model.id) == {model.id: True}
    assert removal_evidence(model)[0] == model.managed_install_dir()
    assert (model.managed_install_dir() / MARKER).is_file()
    # A repeat install reuses complete weights, through both installer entries.
    assert core.install(model.id, install_dependencies=False)
    assert core.install(model.id, install_dependencies=False, on_progress=lambda *_: None)
    assert len(downloads) == 1
    untouched = tmp_path / "models" / "existing-whisper" / "model.bin"
    untouched.parent.mkdir()
    untouched.write_bytes(b"existing weights")
    core.remove(model.id)
    assert not model.managed_install_dir().exists()
    assert untouched.read_bytes() == b"existing weights"


def test_anime_external_weights_are_reused_and_never_overwritten(model, tmp_path, monkeypatch):
    shared = tmp_path / "external"
    put_weights(model, shared / model.install_path)
    monkeypatch.setattr(assets, "sources", lambda: [str(shared)])
    installer = ModelInstaller(project_root=tmp_path)
    monkeypatch.setattr(installer, "_run_with_progress", lambda *_a, **_k: pytest.fail("download"))
    assert model.resolved_install_dir() == shared / model.install_path
    assert installer.install_local_model(model)
    assert installer.install_with_progress(model)
    assert not (shared / model.install_path / MARKER).exists()
    for action in (
        lambda: installer.install_local_model(model, force=True),
        lambda: installer.install_with_progress(model, force=True),
        lambda: installer.remove_local_model(model),
    ):
        with pytest.raises(ValueError, match="只读"):
            action()
    assert (shared / model.install_path / "model.safetensors").is_file()


def test_anime_runtime_repair_is_isolated_and_never_downloads(model, tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(tmp_path)
    runtime = resolver.resolve("anime_whisper")
    runtime.python_executable.parent.mkdir(parents=True)
    runtime.python_executable.touch()
    monkeypatch.setattr(
        resolver,
        "ensure_environment",
        lambda name: runtime if name == runtime.id else pytest.fail(name),
    )
    monkeypatch.setattr(resolver, "compute_mode", lambda: "cpu")
    monkeypatch.setattr(resolver, "build_bootstrap_commands", lambda _: [["bootstrap-cpu"]])
    checked = []
    monkeypatch.setattr(resolver, "verify_compute", lambda p: checked.append(p.id))
    monkeypatch.setattr(resolver, "check_modules", lambda _p, _m: True)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.core.resources.model_service.subprocess.run", run)
    core = ModelService(runtime_resolver=resolver)
    monkeypatch.setattr(
        core,
        "_resolve_installer",
        lambda executable: {
            "extras_cmd": lambda extras, root: [executable, f"{root}[{','.join(extras)}]"],
            "packages_cmd": lambda packages: [executable, *packages],
        },
    )
    monkeypatch.setattr(
        core.installer, "install_local_model", lambda *_a, **_k: pytest.fail("download")
    )
    assert core.prepare_runtime(model.id)
    assert calls[0] == ["bootstrap-cpu"]
    assert all(cmd[0] == str(runtime.python_executable) for cmd in calls[1:])
    assert "[anime_whisper]" in calls[1][1]
    assert checked == ["anime_whisper"]


def test_anime_model_operations_are_exposed_to_existing_http_schema(model):
    from src.api.http.routes.models import list_models
    from src.api.http.schemas.asr import AsrEngineDescriptorResponse
    from src.app.services.capability_descriptor_service import CapabilityDescriptorService

    core = MagicMock()
    core.list_models.return_value = [model]
    service = AppModelService(
        core_service=core, dispatcher=MagicMock(), settings_service=MagicMock()
    )
    response = list_models(svc=service)[0]
    assert response.model_id == "anime-whisper"
    assert response.backend == "anime_whisper"
    assert response.supports_install and response.supports_remove and not response.is_auxiliary
    assert response.runtime_profile == "anime_whisper"
    assert response.install_strategy == "huggingface_snapshot"
    descriptor = AsrEngineDescriptorResponse(
        **CapabilityDescriptorService().get_descriptor("asr", "anime_whisper")
    )
    assert descriptor.default_model == "anime-whisper"
