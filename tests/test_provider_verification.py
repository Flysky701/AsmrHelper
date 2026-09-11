from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from src.api.http.app import create_app
from src.app.services.model_service import ModelService as AppModelService
from src.app.services.resource_service import ResourceService
from src.app.services.settings_service import SettingsService
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_status import ModelStatusResolver
from src.core.resources.provider_verification import (
    ProviderVerificationPersistenceError,
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


def test_provider_status_is_runnable_and_manual_probe_is_cached_without_status_io(monkeypatch):
    config = _Config()
    _patch_config_get(monkeypatch, config)
    registry = ProviderVerificationRegistry()
    probe = MagicMock()
    settings = SettingsService(
        config_manager=config,
        provider_probe=probe,
        verification_registry=registry,
    )
    resolver = ModelStatusResolver(provider_verifications=registry)

    before = resolver.resolve(_entry())
    result = settings.test_provider("deepseek")
    after = resolver.resolve(_entry())
    repeated = resolver.resolve(_entry())

    assert before.executable is True
    assert before.issues[0].code == "PROVIDER_UNVERIFIED"
    assert result.success is True
    assert after.executable is True
    assert repeated.executable is True
    probe.assert_called_once_with(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
    )


def test_failed_manual_probe_records_advisory_status(monkeypatch):
    config = _Config()
    _patch_config_get(monkeypatch, config)
    registry = ProviderVerificationRegistry()
    settings = SettingsService(
        config_manager=config,
        provider_probe=MagicMock(side_effect=RuntimeError("authentication failed")),
        verification_registry=registry,
    )
    resolver = ModelStatusResolver(provider_verifications=registry)

    result = settings.test_provider("deepseek")
    status = resolver.resolve(_entry())

    assert result.success is False
    assert status.executable is True
    assert status.issues[0].code == "PROVIDER_VERIFICATION_FAILED"
    assert "authentication failed" in status.detail


def test_configuration_fingerprint_and_ttl_invalidate_success(monkeypatch):
    clock = _Clock()
    config = _Config()
    _patch_config_get(monkeypatch, config)
    registry = ProviderVerificationRegistry(ttl_seconds=10, clock=clock)
    registry.record_success(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
    )
    resolver = ModelStatusResolver(provider_verifications=registry)

    assert resolver.resolve(_entry()).executable is True

    config.data["api"]["deepseek_base_url"] = "https://gateway.invalid/v1"
    changed = resolver.resolve(_entry())
    assert changed.executable is True
    assert changed.issues[0].code == "PROVIDER_UNVERIFIED"

    config.data["api"]["deepseek_base_url"] = "https://api.deepseek.com"
    config.data["api"]["deepseek_api_key"] = "replacement-key"
    changed_key = resolver.resolve(_entry())
    assert changed_key.executable is True
    assert changed_key.issues[0].code == "PROVIDER_UNVERIFIED"

    config.data["api"]["deepseek_api_key"] = "current-key"
    clock.now += 10
    expired = resolver.resolve(_entry())
    assert expired.executable is True
    assert expired.issues[0].code == "PROVIDER_UNVERIFIED"


def test_successful_verification_survives_registry_restart(tmp_path):
    cache_path = tmp_path / "provider-verifications.json"
    first = ProviderVerificationRegistry(
        ttl_seconds=60,
        clock=_Clock(100),
        storage_path=cache_path,
    )
    first.record_success(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
        message="verified",
    )

    restarted = ProviderVerificationRegistry(
        ttl_seconds=60,
        clock=_Clock(120),
        storage_path=cache_path,
    )

    restored = restarted.get_fresh(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
    )
    assert restored is not None
    assert restored.success is True
    assert restored.message == ""


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


def test_failed_recheck_discards_old_cache_when_atomic_replace_fails(
    monkeypatch,
    tmp_path,
):
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

    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("disk full")))
    registry.record_failure(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
        message="invalid credential",
        error_code="PROVIDER_CONNECTION_FAILED",
    )

    assert cache_path.exists() is False
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


def test_revocation_marker_blocks_locked_old_success_after_restart(
    monkeypatch,
    tmp_path,
):
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
    real_unlink = Path.unlink

    def locked_cache_unlink(path: Path, *args, **kwargs):
        if path == cache_path:
            raise PermissionError("cache file is locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("locked")))
    monkeypatch.setattr(Path, "unlink", locked_cache_unlink)
    registry.record_failure(
        "deepseek",
        "current-key",
        "https://api.deepseek.com",
        message="invalid credential",
        error_code="PROVIDER_CONNECTION_FAILED",
    )

    monkeypatch.undo()
    assert cache_path.exists() is True
    assert cache_path.with_suffix(".json.revoked").exists() is True
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


def test_revocation_marker_is_durable_before_cache_replacement(
    monkeypatch,
    tmp_path,
):
    cache_path = tmp_path / "provider-verifications.json"
    marker_path = cache_path.with_suffix(".json.revoked")
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

    def interrupt_replace(_source, _target):
        assert marker_path.read_text(encoding="utf-8") == "revoked\n"
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(os, "replace", interrupt_replace)
    with pytest.raises(RuntimeError, match="interruption"):
        registry.record_failure(
            "deepseek",
            "current-key",
            "https://api.deepseek.com",
            message="invalid credential",
            error_code="PROVIDER_CONNECTION_FAILED",
        )

    monkeypatch.undo()
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


def test_revocation_storage_total_failure_is_a_hard_error(monkeypatch, tmp_path):
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
    real_unlink = Path.unlink
    real_open = Path.open

    def blocked_open(path: Path, *args, **kwargs):
        if path == cache_path.with_suffix(".json.revoked"):
            raise PermissionError("marker is read-only")
        return real_open(path, *args, **kwargs)

    def blocked_unlink(path: Path, *args, **kwargs):
        if path == cache_path:
            raise PermissionError("cache is locked")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked_open)
    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("locked")))

    with pytest.raises(ProviderVerificationPersistenceError, match="revoked"):
        registry.invalidate_provider("deepseek")


def test_invalidation_discards_old_cache_when_write_fails(monkeypatch, tmp_path):
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
    temporary_path = cache_path.with_suffix(".json.tmp")
    real_open = Path.open

    def blocked_temporary_open(path: Path, *args, **kwargs):
        if path == temporary_path:
            raise OSError("read-only filesystem")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked_temporary_open)

    registry.invalidate_provider("deepseek")

    monkeypatch.setattr(Path, "open", real_open)
    assert cache_path.exists() is False
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


def test_registry_rejects_non_finite_ttl_and_clock(tmp_path):
    with pytest.raises(ValueError, match="TTL"):
        ProviderVerificationRegistry(ttl_seconds=float("nan"))
    with pytest.raises(ValueError, match="TTL"):
        ProviderVerificationRegistry(ttl_seconds=float("inf"))
    with pytest.raises(ValueError, match="clock"):
        ProviderVerificationRegistry(
            clock=lambda: float("nan"),
            storage_path=tmp_path / "provider-verifications.json",
        )


def test_persisted_verification_rejects_unbounded_or_future_timestamps(tmp_path):
    cache_path = tmp_path / "provider-verifications.json"
    records = [
        {
            "provider": "deepseek",
            "configuration_fingerprint": "infinite",
            "success": True,
            "checked_at": 100,
            "expires_at": float("inf"),
        },
        {
            "provider": "deepseek",
            "configuration_fingerprint": "nan",
            "success": True,
            "checked_at": float("nan"),
            "expires_at": 105,
        },
        {
            "provider": "deepseek",
            "configuration_fingerprint": "too-long",
            "success": True,
            "checked_at": 100,
            "expires_at": 1000,
        },
        {
            "provider": "deepseek",
            "configuration_fingerprint": "future",
            "success": True,
            "checked_at": 1000,
            "expires_at": 1010,
        },
    ]
    cache_path.write_text(
        json.dumps({"version": 1, "records": records}),
        encoding="utf-8",
    )

    registry = ProviderVerificationRegistry(
        ttl_seconds=10,
        clock=_Clock(100),
        storage_path=cache_path,
    )

    assert json.loads(cache_path.read_text(encoding="utf-8"))["records"] == []
    assert (
        registry.get_fresh(
            "deepseek",
            "any-key",
            "https://api.deepseek.com",
        )
        is None
    )


def test_corrupt_verification_cache_is_ignored(tmp_path):
    cache_path = tmp_path / "provider-verifications.json"
    cache_path.write_text("not-json", encoding="utf-8")

    registry = ProviderVerificationRegistry(storage_path=cache_path)

    assert (
        registry.get_fresh(
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


def test_batch_verify_includes_cloud_probe_and_explicit_failure(monkeypatch):
    config = _Config()
    _patch_config_get(monkeypatch, config)
    registry = ProviderVerificationRegistry()
    probe = MagicMock(side_effect=RuntimeError("invalid credential"))
    settings = SettingsService(
        config_manager=config,
        provider_probe=probe,
        verification_registry=registry,
    )
    entry = _entry()
    resolver = ModelStatusResolver(provider_verifications=registry)
    core = MagicMock()
    core.verify.return_value = {}
    core.list_models.return_value = [entry]
    core.get_status.side_effect = lambda _model_id: resolver.resolve(entry)
    models = AppModelService(
        core_service=core,
        dispatcher=MagicMock(),
        settings_service=settings,
    )

    results = models.verify_models()

    assert len(results) == 1
    assert results[0].model_id == "deepseek"
    assert results[0].success is False
    assert "invalid credential" in results[0].detail
    core.list_models.assert_called_once_with(kind="cloud")
    probe.assert_called_once()


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
