import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner


def test_model_catalog_loads_local_and_cloud_entries():
    from src.core.resources.model_catalog import ModelCatalog

    catalog = ModelCatalog()

    whisper = catalog.get("faster-whisper-base")
    deepseek = catalog.get("deepseek")

    assert whisper.kind == "local"
    assert whisper.category == "asr"
    assert "config.json" in whisper.required_files

    assert deepseek.kind == "cloud"
    assert deepseek.category == "llm"
    assert deepseek.provider == "deepseek"


def test_model_catalog_rejects_invalid_entry(tmp_path):
    from src.core.resources.model_catalog import ModelCatalogError, load_catalog_file

    bad_yaml = tmp_path / "bad_models.yaml"
    bad_yaml.write_text(
        """
models:
  - id: broken
    kind: local
    category: wrong
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ModelCatalogError):
        load_catalog_file(bad_yaml)


def test_model_status_distinguishes_missing_invalid_and_installed(tmp_path):
    from src.core.resources.model_catalog import load_catalog_file
    from src.core.resources.model_status import ModelStatusResolver

    model_root = tmp_path / "models"
    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text(
        f"""
models:
  - id: test-local
    kind: local
    category: asr
    provider: faster_whisper
    install_root: "{model_root.as_posix()}"
    install_path: "whisper/test-local"
    required_files: ["model.bin", "config.json"]
    required_dirs: []
    supports_install: true
    supports_remove: true
    display_name: "Test Local"
    description: "Test model"
""".strip(),
        encoding="utf-8",
    )

    catalog = load_catalog_file(yaml_path)
    entry = catalog.get("test-local")
    resolver = ModelStatusResolver()

    assert resolver.resolve(entry).status == "missing"

    install_dir = model_root / "whisper" / "test-local"
    install_dir.mkdir(parents=True)
    (install_dir / "model.bin").write_text("x", encoding="utf-8")
    assert resolver.resolve(entry).status == "invalid"

    (install_dir / "config.json").write_text("{}", encoding="utf-8")
    assert resolver.resolve(entry).status == "installed"


def test_cloud_status_depends_on_configured_api_key(monkeypatch):
    from src.core.resources.model_catalog import ModelCatalog
    from src.core.resources.model_status import ModelStatusResolver

    catalog = ModelCatalog()
    entry = catalog.get("deepseek")
    resolver = ModelStatusResolver()

    monkeypatch.setattr("src.config.config._config", {
        "api": {
            "provider": "deepseek",
            "deepseek_api_key": "",
            "openai_api_key": "",
        }
    })
    assert resolver.resolve(entry).status == "unconfigured"

    monkeypatch.setattr("src.config.config._config", {
        "api": {
            "provider": "deepseek",
            "deepseek_api_key": "secret",
            "openai_api_key": "",
        }
    })
    assert resolver.resolve(entry).status == "configured"


def test_model_remove_deletes_files_but_keeps_config(tmp_path):
    from src.core.resources.model_catalog import load_catalog_file
    from src.core.resources.model_installer import ModelInstaller

    project_root = tmp_path
    config_dir = project_root / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text('{"processing": {"asr_model": "large-v3"}}', encoding="utf-8")

    model_root = project_root / "models"
    install_dir = model_root / "whisper" / "to-remove"
    install_dir.mkdir(parents=True)
    (install_dir / "model.bin").write_text("x", encoding="utf-8")
    (install_dir / "config.json").write_text("{}", encoding="utf-8")

    yaml_path = tmp_path / "models.yaml"
    yaml_path.write_text(
        f"""
models:
  - id: test-remove
    kind: local
    category: asr
    provider: faster_whisper
    install_root: "{model_root.as_posix()}"
    install_path: "whisper/to-remove"
    required_files: ["model.bin", "config.json"]
    required_dirs: []
    supports_install: true
    supports_remove: true
    display_name: "Test Remove"
    description: "Test model"
""".strip(),
        encoding="utf-8",
    )

    catalog = load_catalog_file(yaml_path)
    installer = ModelInstaller(project_root=project_root)
    installer.remove_local_model(catalog.get("test-remove"))

    assert not install_dir.exists()
    assert '"asr_model": "large-v3"' in config_path.read_text(encoding="utf-8")


def test_cli_model_commands_surface_local_and_cloud_behaviors(monkeypatch, tmp_path):
    from src.cli import cli

    runner = CliRunner()

    result = runner.invoke(cli, ["model", "list"])
    assert result.exit_code == 0
    assert "faster-whisper-base" in result.output
    assert "deepseek" in result.output

    result = runner.invoke(cli, ["model", "install", "deepseek"])
    assert result.exit_code != 0
    assert "仅支持配置检查" in result.output

    fake_model_dir = tmp_path / "models" / "whisper" / "base"
    fake_model_dir.mkdir(parents=True)
    (fake_model_dir / "model.bin").write_text("x", encoding="utf-8")
    (fake_model_dir / "config.json").write_text("{}", encoding="utf-8")
    (fake_model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ASMR_HELPER_MODEL_ROOT", str(tmp_path / "models"))
    result = runner.invoke(cli, ["model", "status", "faster-whisper-base"])
    assert result.exit_code == 0
    assert "installed" in result.output


def test_verify_models_script_uses_shared_model_service():
    script_path = Path("scripts/verify_models.py")
    content = script_path.read_text(encoding="utf-8")

    assert "ModelService" in content or "get_model_service" in content

