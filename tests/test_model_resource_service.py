from __future__ import annotations

import os
import sys
import threading
import time
from textwrap import dedent

import pytest

from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_installer import ModelInstaller
from src.core.resources.model_service import ModelService
from src.core.resources.model_status import ModelState, ModelStatusResolver


def test_install_family_all_expands_family_members_and_required_assets(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: family-base
                kind: local
                category: asr
                provider: sample
                family_id: sample_family
                display_name: Family Base
                description: Base model
                install_root: models
                install_path: sample/base
                supports_install: true
                install_strategy: huggingface_snapshot
                required_assets: [shared-tokenizer]

              - id: family-large
                kind: local
                category: asr
                provider: sample
                family_id: sample_family
                display_name: Family Large
                description: Large model
                install_root: models
                install_path: sample/large
                supports_install: true
                install_strategy: huggingface_snapshot

              - id: shared-tokenizer
                kind: local
                category: asr
                provider: sample
                family_id: sample_family_assets
                display_name: Shared Tokenizer
                description: Tokenizer asset
                install_root: models
                install_path: sample/tokenizer
                supports_install: true
                install_strategy: huggingface_snapshot
            """
        ).strip(),
        encoding="utf-8",
    )

    service = ModelService(catalog_path=catalog_path)
    installed_ids: list[str] = []

    def fake_install(entry, mirror=None, force=False):
        installed_ids.append(entry.id)
        return True

    service.installer.install_local_model = fake_install

    result = service.install("family-base", install_mode="family_all")

    assert result is True
    assert installed_ids == ["family-base", "shared-tokenizer", "family-large"]


def test_install_stops_before_model_download_when_runtime_dependencies_fail(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: optional-model
                kind: local
                category: asr
                provider: optional
                display_name: Optional Model
                description: Optional model
                install_root: models
                install_path: optional/model
                supports_install: true
                install_strategy: huggingface_snapshot
                upstream_name: example/optional-model
                required_python_extras: [optional]
            """
        ).strip(),
        encoding="utf-8",
    )
    service = ModelService(catalog_path=catalog_path)
    downloaded: list[str] = []
    def fail_dependencies(entry):
        raise RuntimeError("dependency conflict")

    service._install_runtime_packages = fail_dependencies
    service.installer.install_local_model = (
        lambda entry, mirror=None, force=False: downloaded.append(entry.id) or True
    )

    with pytest.raises(RuntimeError, match="dependency conflict"):
        service.install("optional-model")

    assert downloaded == []


def test_runtime_dependency_install_reports_subprocess_failure(
    monkeypatch,
    tmp_path,
):
    entry = ModelEntry(
        id="optional-model",
        kind="local",
        category="asr",
        provider="optional",
        display_name="Optional Model",
        description="test",
        install_root=str(tmp_path),
        install_path="optional/model",
        required_python_extras=["optional"],
    )
    service = ModelService()
    monkeypatch.setattr(
        service,
        "_resolve_installer",
        lambda: {
            "extras_cmd": lambda extras, cwd: ["install-extra"],
            "packages_cmd": lambda packages: ["install-package"],
        },
    )

    class FailedResult:
        returncode = 1
        stderr = "dependency conflict"

    monkeypatch.setattr(
        "src.core.resources.model_service.subprocess.run",
        lambda *args, **kwargs: FailedResult(),
    )

    with pytest.raises(RuntimeError, match="dependency conflict"):
        service._install_runtime_packages(entry)


def test_uv_runtime_dependency_install_targets_running_interpreter(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "uv.exe" if name == "uv" else None)

    installer = ModelService._resolve_installer()

    extras_cmd = installer["extras_cmd"](["kokoro"], "E:/Projects/AsmrHelper")
    packages_cmd = installer["packages_cmd"](["soundfile>=0.12.0"])
    assert extras_cmd[:5] == ["uv.exe", "pip", "install", "--python", sys.executable]
    assert packages_cmd[:5] == ["uv.exe", "pip", "install", "--python", sys.executable]


def test_package_install_with_progress_does_not_start_download(tmp_path, monkeypatch):
    entry = ModelEntry(
        id="kokoro",
        kind="local",
        category="tts",
        provider="kokoro",
        display_name="Kokoro",
        description="test",
        install_root=str(tmp_path),
        install_path="kokoro",
        supports_install=True,
        install_strategy="package",
    )
    installer = ModelInstaller(project_root=tmp_path)
    monkeypatch.setattr(installer, "verify_local_model", lambda current: True)
    monkeypatch.setattr(
        installer,
        "_run_with_progress",
        lambda *args, **kwargs: pytest.fail("package installs must not start a download subprocess"),
    )
    progress: list[tuple[float, str]] = []

    installed = installer.install_with_progress(
        entry,
        on_progress=lambda fraction, message: progress.append((fraction, message)),
    )

    assert installed is True
    assert progress == [(1.0, "runtime packages installed")]


def test_model_installs_are_serialized(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: first
                kind: local
                category: asr
                provider: sample
                display_name: First
                description: test
                install_root: models
                install_path: first
                supports_install: true
                install_strategy: huggingface_snapshot
                upstream_name: sample/first
              - id: second
                kind: local
                category: asr
                provider: sample
                display_name: Second
                description: test
                install_root: models
                install_path: second
                supports_install: true
                install_strategy: huggingface_snapshot
                upstream_name: sample/second
            """
        ).strip(),
        encoding="utf-8",
    )
    service = ModelService(catalog_path=catalog_path)
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    def fake_install(entry, mirror=None, force=False):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with counter_lock:
            active -= 1
        return True

    service.installer.install_local_model = fake_install
    threads = [
        threading.Thread(target=service.install, args=(model_id,))
        for model_id in ("first", "second")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert max_active == 1


def test_download_environment_uses_large_model_timeouts(monkeypatch):
    monkeypatch.delenv("HF_HUB_ETAG_TIMEOUT", raising=False)
    monkeypatch.delenv("HF_HUB_DOWNLOAD_TIMEOUT", raising=False)
    env = ModelInstaller._build_download_env(None)

    assert int(env["HF_HUB_ETAG_TIMEOUT"]) >= 30
    assert int(env["HF_HUB_DOWNLOAD_TIMEOUT"]) >= 120


def test_download_subprocess_error_is_propagated(tmp_path):
    with pytest.raises(RuntimeError, match="ReadTimeout while downloading model"):
        ModelInstaller._run_with_progress(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('ReadTimeout while downloading model'); sys.exit(1)",
            ],
            dict(os.environ),
            timeout=10,
            on_progress=None,
            cwd=str(tmp_path),
        )


def test_installed_assets_are_not_executable_when_python_dependency_is_missing(tmp_path):
    install_dir = tmp_path / "whisper" / "base"
    install_dir.mkdir(parents=True)
    (install_dir / "model.bin").write_bytes(b"model")
    entry = ModelEntry(
        id="faster-whisper-base",
        kind="local",
        category="asr",
        provider="faster_whisper",
        display_name="Faster Whisper Base",
        description="test",
        install_root=str(tmp_path),
        install_path="whisper/base",
        required_files=["model.bin"],
        install_strategy="whisper",
    )
    resolver = ModelStatusResolver(
        import_checker=lambda module: module != "faster_whisper",
    )

    status = resolver.resolve(entry)

    assert status.status == ModelState.INSTALLED
    assert status.executable is False
    assert status.issues[0].code == "PYTHON_DEPENDENCY_MISSING"
    assert status.issues[0].requirement == "faster_whisper"


def test_installed_assets_are_executable_when_runtime_requirements_are_ready(tmp_path):
    install_dir = tmp_path / "whisper" / "base"
    install_dir.mkdir(parents=True)
    (install_dir / "model.bin").write_bytes(b"model")
    entry = ModelEntry(
        id="faster-whisper-base",
        kind="local",
        category="asr",
        provider="faster_whisper",
        display_name="Faster Whisper Base",
        description="test",
        install_root=str(tmp_path),
        install_path="whisper/base",
        required_files=["model.bin"],
        install_strategy="whisper",
    )
    resolver = ModelStatusResolver(import_checker=lambda module: True)

    status = resolver.resolve(entry)

    assert status.status == ModelState.INSTALLED
    assert status.executable is True
    assert status.issues == ()


def test_nested_file_does_not_satisfy_required_top_level_asset(tmp_path):
    install_dir = tmp_path / "qwen3tts" / "custom-voice"
    nested_dir = install_dir / "speech_tokenizer"
    nested_dir.mkdir(parents=True)
    (nested_dir / "model.safetensors").write_bytes(b"tokenizer")
    entry = ModelEntry(
        id="qwen3-custom-voice",
        kind="local",
        category="tts",
        provider="qwen3",
        display_name="Qwen3 CustomVoice",
        description="test",
        install_root=str(tmp_path),
        install_path="qwen3tts/custom-voice",
        required_files=["model.safetensors"],
        install_strategy="qwen3",
    )
    resolver = ModelStatusResolver(import_checker=lambda module: True)

    status = resolver.resolve(entry)

    assert status.status == ModelState.INVALID
    assert status.issues[0].requirement == "model.safetensors"


def test_system_tool_requirement_is_reported_separately(tmp_path):
    entry = ModelEntry(
        id="kokoro",
        kind="local",
        category="tts",
        provider="kokoro",
        display_name="Kokoro",
        description="test",
        install_root=str(tmp_path),
        install_path="kokoro",
        install_strategy="package",
        required_system_tools=["espeak-ng"],
    )
    resolver = ModelStatusResolver(
        import_checker=lambda module: True,
        tool_checker=lambda tool: False,
    )

    status = resolver.resolve(entry)

    assert status.status == ModelState.INSTALLED
    assert status.executable is False
    assert status.issues[0].code == "SYSTEM_TOOL_MISSING"
