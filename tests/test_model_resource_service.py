from __future__ import annotations

from textwrap import dedent

from src.core.resources.model_catalog import ModelEntry
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
