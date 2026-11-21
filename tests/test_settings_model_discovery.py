from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.http import dependencies
from src.api.http.app import create_app
from src.app.services.settings_service import ProviderModelsError, SettingsService
from src.core.resources.provider_verification import ProviderVerificationRegistry


class Config:
    def __init__(self):
        self.data = {"api": {
            "deepseek_api_key": "saved-secret", "deepseek_base_url": "https://saved.invalid/v1",
            "openai_api_key": "openai-secret", "openai_base_url": "https://openai.invalid/v1",
        }}

    def build_effective_config(self, config_override=None):
        result = deepcopy(self.data)
        for section, values in (config_override or {}).items():
            result.setdefault(section, {}).update(values)
        return result


def service(probe):
    return SettingsService(config_manager=Config(), model_probe=probe,
                           verification_registry=ProviderVerificationRegistry())


def test_missing_key_does_not_request_models():
    probe = MagicMock()
    svc = service(probe)
    svc.config.data["api"]["deepseek_api_key"] = ""
    with pytest.raises(ProviderModelsError) as caught:
        svc.discover_models("deepseek")
    assert caught.value.code == "PROVIDER_CREDENTIAL_MISSING"
    probe.assert_not_called()


def test_http_discovery_contract_and_safe_failure():
    probe = MagicMock(return_value=["model-from-service"])
    app = create_app()
    app.dependency_overrides[dependencies.settings_service] = lambda: service(probe)
    client = TestClient(app)
    response = client.post("/api/v1/settings/models", json={"provider": "deepseek"})
    assert response.status_code == 200
    assert response.json() == {"provider": "deepseek", "models": ["model-from-service"]}
    probe.side_effect = TimeoutError("secret")
    response = client.post("/api/v1/settings/models", json={"provider": "deepseek"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "PROVIDER_TIMEOUT"
    assert "secret" not in response.text
