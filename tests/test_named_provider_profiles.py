"""Connection isolation and real Config disk migration (no network calls)."""
import importlib
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.app.errors import AppValidationError
from src.app.services.settings_service import SettingsService, ProviderModelsError


@pytest.fixture
def service(tmp_path, monkeypatch):
    module = importlib.import_module("src.config")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = object.__new__(module.Config)
    cfg.save({"api": {"provider": "deepseek", "deepseek_api_key": "legacy-secret",
                      "deepseek_model": "legacy-model"},
              "external_tts": {"api_key": "tts-old", "model": "voice-model", "voice": "old-voice",
                               "instructions": "old-instruction", "api_format": "speech"}})
    cfg.reload()
    return SettingsService(config_manager=cfg, model_probe=Mock(return_value=["model-a"]))


def create(service, name="Personal", **kwargs):
    return service.update_settings({"connection_profile": {
        "kind": "llm", "name": name, "provider": "openai", "model": "model-a",
        "base_url": "https://personal.invalid/v1", "credential": "personal-secret", **kwargs,
    }})


def test_migration_and_masked_roundtrip(service):
    initial = service.get_settings()
    assert initial["connection_profiles"]["active_llm"] == "legacy-deepseek"
    assert initial["connection_profiles"]["llm"][1]["model"] == initial["providers"]["openai"]["model"]
    result = create(service)
    selected = result["connection_profiles"]["active_llm"]
    assert selected != "legacy-openai"
    assert result["providers"]["default_llm"] == "openai"
    assert result["providers"]["openai"]["model"] == "model-a"
    assert "secret" not in json.dumps(result)
    service.config.reload()
    assert service.get_settings() == result
    service.update_settings({"active_connections": {"llm": "legacy-deepseek"}})
    assert service.config.get("api.deepseek_api_key") == "legacy-secret"
    assert service.config.get("external_tts.instructions") == "old-instruction"


def test_concurrent_profile_saves_do_not_lose_connections(service):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: create(service, name=name), ["First", "Second"]))
    assert len(results) == 2
    names = {p["name"] for p in service.get_settings()["connection_profiles"]["llm"]}
    assert {"First", "Second"} <= names


def test_rename_blank_secret_and_new_profile_isolation(service):
    selected = create(service)["connection_profiles"]["active_llm"]
    result = create(service, name="Renamed", id=selected, credential="")
    assert len(result["connection_profiles"]["llm"]) == 3
    assert service.config.get("api.openai_api_key") == "personal-secret"
    before = deepcopy(service.config.get_file_config())
    with pytest.raises(AppValidationError, match="API Key"):
        create(service, name="Empty", credential="")
    assert service.config.get_file_config() == before


def test_candidate_probe_never_reuses_other_profile_secret(service):
    selected = create(service)["connection_profiles"]["active_llm"]
    before = deepcopy(service.config.get_file_config())
    assert service.discover_models("openai", {"connection_profile": {
        "kind": "llm", "id": selected, "name": "Personal", "base_url": "https://draft.invalid/v1", "credential": "",
    }}) == ["model-a"]
    service._model_probe.assert_called_once_with("openai", "personal-secret", "https://draft.invalid/v1")
    with pytest.raises(ProviderModelsError, match="API Key"):
        service.discover_models("openai", {"connection_profile": {
            "kind": "llm", "name": "New", "provider": "openai", "model": "",
            "base_url": "https://draft.invalid/v1", "credential": "",
        }})
    assert service.config.get_file_config() == before


def test_env_applies_only_to_legacy_profiles_and_is_not_persisted(service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    create(service)
    assert service.config.get("api.openai_api_key") == "personal-secret"
    assert "environment-secret" not in json.dumps(service.config.get_file_config())
    service.update_settings({"active_connections": {"llm": "legacy-openai"}})
    assert service.config.get("api.openai_api_key") == "environment-secret"
