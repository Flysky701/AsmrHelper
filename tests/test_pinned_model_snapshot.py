import hashlib
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from src.core.resources import model_assets, pinned_snapshot
from src.core.resources.model_catalog import ModelCatalog
from src.core.resources.model_installer import ModelInstaller


@pytest.fixture
def drama(tmp_path, monkeypatch):
    original = ModelCatalog().get("fish_drama3")
    config, codec = b"{}", b"fixture codec"
    manifest = {
        "config.json": (len(config), hashlib.sha1(b"blob 2\0" + config).hexdigest()),
        "codec.pth": (len(codec), hashlib.sha256(codec).hexdigest()),
    }
    model = replace(original, snapshot_files=manifest, required_files=list(manifest))
    monkeypatch.setattr(model_assets, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(model_assets, "sources", lambda: [])
    monkeypatch.setattr(type(model), "resolved_install_root", lambda entry: tmp_path / "models")
    monkeypatch.setenv("ASMR_HELPER_HF_FALLBACK", "none")
    return model, {"config.json": config, "codec.pth": codec}


def test_drama3_catalog_pins_complete_official_snapshot():
    model = ModelCatalog().get("fish_drama3")
    assert model.snapshot_revision == "78e5ab79e49aa9a25abe8799eff2c4d73a1c3216"
    assert model.install_path == "fish_drama3"
    assert len(model.required_files) == len(model.snapshot_files) == 25
    assert sum(size for size, _ in model.snapshot_files.values()) == 41_502_571_262
    assert sum(len(digest) == 64 for _, digest in model.snapshot_files.values()) == 17


def test_install_verifies_files_and_can_resume_in_place(drama, monkeypatch):
    model, contents = drama
    directory = model.resolved_install_dir()
    installer = ModelInstaller()
    calls = []
    corrupted = True

    def response(request):
        filename = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path == f"/fishaudio/drama-3/resolve/{model.snapshot_revision}/{filename}"
        calls.append(filename)
        data = contents[filename]
        if corrupted and filename == "codec.pth":
            data = bytes(len(data))
        return httpx.Response(200, content=data)

    client = httpx.Client(transport=httpx.MockTransport(response))
    monkeypatch.setattr(pinned_snapshot.httpx, "Client", lambda **kwargs: client)
    with pytest.raises(ValueError, match="哈希"):
        installer.install_with_progress(model, mirror="huggingface")
    assert (directory / "config.json").read_bytes() == contents["config.json"]
    assert not (directory / "codec.pth").exists()
    assert not list(directory.glob("*.part"))
    assert not installer.verify_local_model(model)

    corrupted = False
    client = type(client)(transport=httpx.MockTransport(response))
    assert installer.install_local_model(model, mirror="huggingface")
    assert installer.verify_local_model(model)
    assert installer.install_local_model(model, mirror="huggingface")
    assert calls == ["config.json", "codec.pth", "codec.pth"]

    (directory / "codec.pth").write_bytes(bytes(len(contents["codec.pth"])))
    with pytest.raises(ValueError, match="现有模型文件"):
        installer.install_local_model(model, mirror="huggingface")
    assert calls == ["config.json", "codec.pth", "codec.pth"]
    client = type(client)(transport=httpx.MockTransport(response))
    assert installer.install_local_model(model, mirror="huggingface", force=True)
    assert calls[-1] == "codec.pth"
    assert (directory / "codec.pth").read_bytes() == contents["codec.pth"]


def test_install_checks_disk_before_network_or_creating_directory(drama, monkeypatch):
    model, _ = drama
    monkeypatch.setattr(pinned_snapshot.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    monkeypatch.setattr(pinned_snapshot.httpx, "Client", lambda **kwargs: pytest.fail("network requested"))
    with pytest.raises(ValueError, match="磁盘空间"):
        ModelInstaller().install_local_model(model, mirror="huggingface")
    assert not model.managed_install_dir().exists()


def test_offline_model_discovery_recognizes_only_complete_pinned_snapshot(drama, monkeypatch, tmp_path):
    model, contents = drama
    source = tmp_path / "shared"
    snapshots = source / "models--fishaudio--drama-3" / "snapshots"
    for revision in ("a" * 40, model.snapshot_revision):
        directory = snapshots / revision
        directory.mkdir(parents=True)
        for name, data in contents.items():
            (directory / name).write_bytes(data)
    pinned = snapshots / model.snapshot_revision
    monkeypatch.setattr(model_assets, "sources", lambda: [str(source)])
    assert model.resolved_install_dir() == pinned
    assert model_assets.shared(model)
    (pinned / "codec.pth").write_bytes(b"truncated")
    assert model.resolved_install_dir() == model.managed_install_dir()
