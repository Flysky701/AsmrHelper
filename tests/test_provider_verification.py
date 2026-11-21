from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.api.http.app import create_app
from src.app.services.model_service import ModelService as AppModelService
from src.app.services.resource_service import ResourceService
from src.app.services.settings_service import SettingsService
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_status import ModelStatusResolver
from src.core.resources.provider_verification import (
    ProviderVerificationRegistry,
)


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Config:
    def __init__(self) -> None:
        self.data = {
            "api": {
                "provider": "deepseek",
                "deepseek_api_key": "current-key",
                "deepseek_base_url": "https://api.deepseek.com",
            }
        }

    def to_dict(self):
        return deepcopy(self.data)

    def build_effective_config(self, config_override=None):
        candidate = self.to_dict()
        for section, values in (config_override or {}).items():
            if isinstance(values, dict):
                candidate.setdefault(section, {}).update(values)
            else:
                candidate[section] = values
        return candidate


def _entry() -> ModelEntry:
    return ModelEntry(
        id="deepseek",
        kind="cloud",
        category="llm",
        provider="deepseek",
        display_name="DeepSeek API",
        description="test",
        capability_models=["deepseek-chat"],
        api_key_config="api.deepseek_api_key",
    )


def _patch_config_get(monkeypatch, config: _Config) -> None:
    def get_value(key: str, default=None):
        value = config.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    monkeypatch.setattr("src.core.resources.model_status.config.get", get_value)


def test_persisted_verification_expires_and_never_contains_credentials(tmp_path):
    cache_path = tmp_path / "provider-verifications.json"
    registry = ProviderVerificationRegistry(
        ttl_seconds=10,
        clock=_Clock(100),
        storage_path=cache_path,
    )
    registry.record_success(
        "deepseek",
        "super-secret-key",
        "https://api.deepseek.com",
    )

    serialized = cache_path.read_text(encoding="utf-8")
    assert "super-secret-key" not in serialized
    assert "https://api.deepseek.com" not in serialized

    restarted = ProviderVerificationRegistry(
        ttl_seconds=10,
        clock=_Clock(110),
        storage_path=cache_path,
    )
    assert (
        restarted.get_fresh(
            "deepseek",
            "super-secret-key",
            "https://api.deepseek.com",
        )
        is None
    )
    assert json.loads(cache_path.read_text(encoding="utf-8"))["records"] == []


def test_failed_recheck_removes_persisted_success(tmp_path):
    cache_path = tmp_path / "provider-verifications.json"
    registry = ProviderVerificationRegistry(
        ttl_seconds=60,
        clock=_Clock(100),
        storage_path=cache_path,
    )
    registry.record_success(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
    )
    registry.record_failure(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
        message="invalid credential",
        error_code="PROVIDER_CONNECTION_FAILED",
    )

    restarted = ProviderVerificationRegistry(
        ttl_seconds=60,
        clock=_Clock(101),
        storage_path=cache_path,
    )
    assert (
        restarted.get_fresh(
            "deepseek",
            "current-key",
            "https://api.deepseek.com",
        )
        is None
    )


def test_successful_draft_probe_does_not_unlock_different_saved_configuration(monkeypatch):
    config = _Config()
    _patch_config_get(monkeypatch, config)
    registry = ProviderVerificationRegistry()
    settings = SettingsService(
        config_manager=config,
        provider_probe=MagicMock(),
        verification_registry=registry,
    )
    resolver = ModelStatusResolver(provider_verifications=registry)

    result = settings.test_provider(
        "deepseek",
        {
            "providers": {
                "deepseek": {
                    "credential": "draft-key",
                    "base_url": "https://draft.invalid/v1",
                }
            }
        },
    )

    assert result.success is True
    assert resolver.resolve(_entry()).executable is True


def test_cloud_verification_is_advisory_for_pipeline_readiness(monkeypatch, tmp_path):
    config = _Config()
    _patch_config_get(monkeypatch, config)
    clock = _Clock()
    registry = ProviderVerificationRegistry(ttl_seconds=10, clock=clock)
    probe = MagicMock()
    settings = SettingsService(
        config_manager=config,
        provider_probe=probe,
        verification_registry=registry,
    )
    entry = _entry()
    resolver = ModelStatusResolver(provider_verifications=registry)
    core = MagicMock()
    core.get_model.return_value = entry
    core.list_models.return_value = [entry]
    core.get_status.side_effect = lambda _model_id: resolver.resolve(entry)
    models = AppModelService(
        core_service=core,
        dispatcher=MagicMock(),
        settings_service=settings,
    )
    descriptors = MagicMock()
    descriptors.get_descriptor.return_value = {
        "supported_models": ["deepseek-chat"],
        "default_model": "deepseek-chat",
        "runtime_requirements": {
            "python_modules": [],
            "system_tools": [],
        },
    }
    resources = ResourceService(
        project_root=tmp_path,
        descriptor_service=descriptors,
        model_service=models,
    )
    resources.ensure_workspace()
    profile = {
        "stages": {
            "translate": {
                "enabled": True,
                "provider": "deepseek",
                "model": "deepseek-chat",
            }
        }
    }

    before = resources.check_task_readiness(
        task_type="pipeline",
        execution_profile=profile,
    )
    verification = models.verify_models("deepseek")
    after = resources.check_task_readiness(
        task_type="pipeline",
        execution_profile=profile,
    )
    clock.now += 10
    expired = resources.check_task_readiness(
        task_type="pipeline",
        execution_profile=profile,
    )
    probe.side_effect = RuntimeError("authentication failed")
    failed_verification = models.verify_models("deepseek")
    after_failed_verification = resources.check_task_readiness(
        task_type="pipeline",
        execution_profile=profile,
    )

    assert before["ready"] is True
    assert before["issues"] == []
    assert verification[0].success is True
    assert after["ready"] is True
    assert expired["ready"] is True
    assert expired["issues"] == []
    assert failed_verification[0].success is False
    assert after_failed_verification["ready"] is True
    assert after_failed_verification["issues"] == []
    assert probe.call_count == 2


def test_default_http_model_verify_records_status_without_status_probe(monkeypatch):
    import src.app.services.model_service as app_model_module
    import src.app.services.settings_service as settings_module
    import src.core.resources.model_service as core_model_module
    import src.core.resources.provider_verification as verification_module
    from src.config import config as global_config

    config = _Config()
    registry = ProviderVerificationRegistry()
    probe = MagicMock()

    def get_value(key: str, default=None):
        value = config.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    monkeypatch.setattr(global_config, "get", get_value)
    monkeypatch.setattr(global_config, "to_dict", config.to_dict)
    monkeypatch.setattr(verification_module, "_registry", registry)
    monkeypatch.setattr(settings_module, "_service", None)
    monkeypatch.setattr(core_model_module, "_service", None)
    monkeypatch.setattr(app_model_module, "_service", None)
    monkeypatch.setattr(
        SettingsService,
        "_probe_openai_compatible",
        staticmethod(probe),
    )

    with TestClient(create_app()) as client:
        before = client.get("/api/v1/models/deepseek/status")
        verified = client.post("/api/v1/models/deepseek/verify")
        after = client.get("/api/v1/models/deepseek/status")
        statuses = client.get("/api/v1/models/statuses?kind=cloud")

    assert before.status_code == 200
    assert before.json()["executable"] is True
    assert verified.status_code == 200
    assert verified.json()[0]["success"] is True
    assert after.status_code == 200
    assert after.json()["executable"] is True
    assert statuses.status_code == 200
    assert next(
        item for item in statuses.json() if item["model_id"] == "deepseek"
    )["executable"] is True
    probe.assert_called_once_with(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
    )
