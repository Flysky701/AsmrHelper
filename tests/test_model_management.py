import importlib.util
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

    monkeypatch.setattr(
        "src.config.config._config",
        {
            "api": {
                "provider": "deepseek",
                "deepseek_api_key": "",
                "openai_api_key": "",
            }
        },
    )
    assert resolver.resolve(entry).status == "unconfigured"

    monkeypatch.setattr(
        "src.config.config._config",
        {
            "api": {
                "provider": "deepseek",
                "deepseek_api_key": "secret",
                "openai_api_key": "",
            }
        },
    )
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
    assert "deepseek" in result.output

    fake_model_dir = tmp_path / "models" / "whisper" / "base"
    fake_model_dir.mkdir(parents=True)
    (fake_model_dir / "model.bin").write_text("x", encoding="utf-8")
    (fake_model_dir / "config.json").write_text("{}", encoding="utf-8")
    (fake_model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ASMR_HELPER_MODEL_ROOT", str(tmp_path / "models"))
    result = runner.invoke(cli, ["model", "status", "faster-whisper-base"])
    assert result.exit_code == 0
    assert "installed" in result.output


def test_cli_model_queries_use_application_model_service(monkeypatch):
    from src.cli import cli

    calls = {"list": 0, "status": 0}

    class DummyAppModelService:
        def list_models(self, kind=None, category=None):
            calls["list"] += 1
            return [
                type(
                    "Summary",
                    (),
                    {
                        "model_id": "demo-model",
                        "kind": "local",
                        "category": "asr",
                        "backend": "faster_whisper",
                        "display_name": "Demo Model",
                    },
                )()
            ]

        def get_model_status(self, model_id):
            calls["status"] += 1
            return type(
                "StatusView",
                (),
                {"model_id": model_id, "status": "installed", "detail": "ready"},
            )()

        def list_model_statuses(self, kind=None, category=None):
            calls["status"] += 1
            return [
                type(
                    "StatusView",
                    (),
                    {"model_id": "demo-model", "status": "installed", "detail": "ready"},
                )()
            ]

    monkeypatch.setattr("src.cli.get_app_model_service", lambda: DummyAppModelService())

    runner = CliRunner()
    list_result = runner.invoke(cli, ["model", "list"])
    status_result = runner.invoke(cli, ["model", "status", "demo-model"])

    assert list_result.exit_code == 0
    assert status_result.exit_code == 0
    assert "demo-model" in list_result.output
    assert "installed" in status_result.output
    assert calls["list"] == 1
    assert calls["status"] >= 1


def test_application_model_service_wraps_model_lifecycle_operations():
    from src.app.dto import ModelOperationResult, ModelVerificationResult
    from src.app.services.model_service import ModelService

    calls = {"install": [], "verify": [], "remove": []}

    class DummyEntry:
        def __init__(self, model_id, kind="local"):
            self.id = model_id
            self.kind = kind

    class DummyStatus:
        def __init__(self, model_id, status, detail):
            self.model_id = model_id
            self.status = status
            self.detail = detail

    class DummyCoreService:
        def get_model(self, model_id):
            return DummyEntry(model_id)

        def get_status(self, model_id):
            if model_id == "demo-remove":
                return DummyStatus(model_id, "missing", "removed")
            if model_id == "demo-invalid":
                return DummyStatus(model_id, "invalid", "missing config.json")
            return DummyStatus(model_id, "installed", "ready")

        def install(self, model_id, mirror=None, force=False):
            calls["install"].append((model_id, mirror, force))
            return True

        def verify(self, model_id=None):
            calls["verify"].append(model_id)
            return {"demo-install": True, "demo-invalid": False}

        def remove(self, model_id):
            calls["remove"].append(model_id)

    service = ModelService(core_service=DummyCoreService())

    install_result = service.install_model("demo-install", mirror="https://hf-mirror.test", force=True)
    verify_results = service.verify_models()
    remove_result = service.remove_model("demo-remove")

    assert calls["install"] == [("demo-install", "https://hf-mirror.test", True)]
    assert calls["verify"] == [None]
    assert calls["remove"] == ["demo-remove"]
    assert install_result == ModelOperationResult(
        action="install",
        model_id="demo-install",
        success=True,
        status="installed",
        detail="ready",
    )
    assert verify_results == [
        ModelVerificationResult(
            model_id="demo-install",
            success=True,
            status="installed",
            detail="ready",
        ),
        ModelVerificationResult(
            model_id="demo-invalid",
            success=False,
            status="invalid",
            detail="missing config.json",
        ),
    ]
    assert remove_result == ModelOperationResult(
        action="remove",
        model_id="demo-remove",
        success=True,
        status="missing",
        detail="removed",
    )


def test_application_model_service_verifies_cloud_model_from_status():
    from src.app.dto import ModelVerificationResult
    from src.app.services.model_service import ModelService

    class DummyEntry:
        def __init__(self, model_id, kind="cloud"):
            self.id = model_id
            self.kind = kind

    class DummyStatus:
        def __init__(self, model_id, status, detail):
            self.model_id = model_id
            self.status = status
            self.detail = detail

    class DummyCoreService:
        def get_model(self, model_id):
            return DummyEntry(model_id)

        def get_status(self, model_id):
            return DummyStatus(model_id, "configured", "api key set")

        def verify(self, model_id=None):
            raise AssertionError("cloud verification should not call local verify()")

    service = ModelService(core_service=DummyCoreService())

    assert service.verify_models("deepseek") == [
        ModelVerificationResult(
            model_id="deepseek",
            success=True,
            status="configured",
            detail="api key set",
        )
    ]


def test_application_model_service_maps_validation_and_execution_errors():
    from src.app.errors import AppExecutionError, AppValidationError
    from src.app.services.model_service import ModelService

    class DummyEntry:
        def __init__(self, model_id):
            self.id = model_id
            self.kind = "local"

    class DummyStatus:
        def __init__(self, model_id, status, detail):
            self.model_id = model_id
            self.status = status
            self.detail = detail

    class DummyCoreService:
        def get_model(self, model_id):
            if model_id == "unknown":
                raise ValueError("unknown model")
            return DummyEntry(model_id)

        def get_status(self, model_id):
            return DummyStatus(model_id, "installed", "ready")

        def install(self, model_id, mirror=None, force=False):
            if model_id == "broken":
                return False
            raise RuntimeError("network error")

        def verify(self, model_id=None):
            raise RuntimeError("verify failed")

        def remove(self, model_id):
            raise ValueError("cannot remove")

    service = ModelService(core_service=DummyCoreService())

    with pytest.raises(AppValidationError, match="unknown model"):
        service.install_model("unknown")

    with pytest.raises(AppExecutionError, match="model install failed: broken"):
        service.install_model("broken")

    with pytest.raises(AppExecutionError, match="network error"):
        service.install_model("demo")

    with pytest.raises(AppExecutionError, match="verify failed"):
        service.verify_models()

    with pytest.raises(AppValidationError, match="cannot remove"):
        service.remove_model("demo")


def test_cli_model_lifecycle_commands_use_application_model_service(monkeypatch):
    from src.cli import cli

    calls = {"install": [], "verify": [], "remove": []}

    class DummyAppModelService:
        def install_model(self, model_id, mirror=None, force=False):
            calls["install"].append((model_id, mirror, force))
            return type("Operation", (), {"model_id": model_id, "status": "installed"})()

        def verify_models(self, model_id=None):
            calls["verify"].append(model_id)
            return [
                type(
                    "Verification",
                    (),
                    {
                        "model_id": model_id or "demo-model",
                        "success": True,
                        "status": "installed",
                        "detail": "ready",
                    },
                )()
            ]

        def remove_model(self, model_id):
            calls["remove"].append(model_id)
            return type("Operation", (), {"model_id": model_id, "status": "missing"})()

    monkeypatch.setattr("src.cli.get_app_model_service", lambda: DummyAppModelService())

    runner = CliRunner()
    install_result = runner.invoke(
        cli,
        ["model", "install", "demo-model", "--mirror", "https://hf-mirror.test", "--force"],
    )
    verify_result = runner.invoke(cli, ["model", "verify", "demo-model"])
    remove_result = runner.invoke(cli, ["model", "remove", "demo-model"])

    assert install_result.exit_code == 0
    assert verify_result.exit_code == 0
    assert remove_result.exit_code == 0
    assert "Model installed: demo-model [installed]" in install_result.output
    assert "demo-model: installed (ready)" in verify_result.output
    assert "Model removed: demo-model [missing]" in remove_result.output
    assert calls["install"] == [("demo-model", "https://hf-mirror.test", True)]
    assert calls["verify"] == ["demo-model"]
    assert calls["remove"] == ["demo-model"]


def test_cli_model_verify_fails_when_any_result_is_invalid(monkeypatch):
    from src.cli import cli

    class DummyAppModelService:
        def verify_models(self, model_id=None):
            return [
                type(
                    "Verification",
                    (),
                    {
                        "model_id": "broken-model",
                        "success": False,
                        "status": "invalid",
                        "detail": "missing config.json",
                    },
                )()
            ]

    monkeypatch.setattr("src.cli.get_app_model_service", lambda: DummyAppModelService())

    runner = CliRunner()
    result = runner.invoke(cli, ["model", "verify"])

    assert result.exit_code != 0
    assert "broken-model: invalid (missing config.json)" in result.output
    assert "Some models failed verification" in result.output


def test_verify_models_script_main_uses_shared_model_service(monkeypatch, capsys):
    import src.core.resources as core_resources

    script_path = Path("scripts/verify_models.py")
    captured = {"called": False, "kind": None}

    class DummyStatus:
        def __init__(self, model_id, status, detail, path=None):
            self.model_id = model_id
            self.status = status
            self.detail = detail
            self.path = path

    class DummyService:
        def get_all_statuses(self, kind=None):
            captured["kind"] = kind
            return [DummyStatus("demo-model", "installed", "ready", "models/demo-model")]

    def fake_get_model_service():
        captured["called"] = True
        return DummyService()

    monkeypatch.setattr(core_resources, "get_model_service", fake_get_model_service)

    spec = importlib.util.spec_from_file_location("verify_models_test_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.main()
    stdout = capsys.readouterr().out

    assert result == 0
    assert captured["called"] is True
    assert captured["kind"] == "local"
    assert "Model Status" in stdout
    assert "[demo-model] installed" in stdout
    assert "All models verified successfully!" in stdout
