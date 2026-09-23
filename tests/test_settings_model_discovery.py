from copy import deepcopy
from types import SimpleNamespace
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


@pytest.mark.parametrize("credential", ["", "***configured***", None])
def test_draft_discovery_preserves_secret_and_does_not_save(credential):
    probe = MagicMock(return_value=["z-model", "a-model", "z-model"])
    svc = service(probe)
    before = deepcopy(svc.config.data)
    models = svc.discover_models("deepseek", {"providers": {"deepseek": {
        "base_url": "https://draft.invalid/v1", "credential": credential,
    }}})
    assert models == ["a-model", "z-model"]
    probe.assert_called_once_with("deepseek", "saved-secret", "https://draft.invalid/v1")
    assert svc.config.data == before


def test_openai_uses_its_own_draft_connection_and_empty_list_has_no_fallback():
    probe = MagicMock(return_value=[])
    svc = service(probe)
    assert svc.discover_models("openai", {"providers": {"openai": {
        "credential": "draft-secret", "base_url": "https://draft.invalid/v1",
    }}}) == []
    probe.assert_called_once_with("openai", "draft-secret", "https://draft.invalid/v1")


@pytest.mark.parametrize("ids", [None, {}, [None], [""], ["bad model"], ["x\x00"], [42], ["x" * 513]])
def test_invalid_model_ids_are_not_exposed(ids):
    with pytest.raises(ProviderModelsError) as caught:
        service(MagicMock(return_value=ids)).discover_models("deepseek")
    assert caught.value.code == "PROVIDER_MODELS_INVALID"


@pytest.mark.parametrize("status,code", [
    (401, "PROVIDER_AUTH_FAILED"), (403, "PROVIDER_AUTH_FAILED"),
    (404, "PROVIDER_MODELS_UNSUPPORTED"), (429, "PROVIDER_RATE_LIMITED"),
    (500, "PROVIDER_CONNECTION_FAILED"),
])
def test_discovery_error_codes_never_include_upstream_secrets(status, code):
    exc = RuntimeError("url has saved-secret and another-secret")
    exc.status_code = status
    with pytest.raises(ProviderModelsError) as caught:
        service(MagicMock(side_effect=exc)).discover_models("deepseek")
    assert caught.value.code == code
    assert "secret" not in str(caught.value)


def test_timeout_has_distinct_code():
    with pytest.raises(ProviderModelsError) as caught:
        service(MagicMock(side_effect=TimeoutError())).discover_models("deepseek")
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert caught.value.status_code == 504


@pytest.mark.parametrize("provider,updates,code", [
    ("unknown", {}, "PROVIDER_NOT_FOUND"),
    ("deepseek", {"api": {"deepseek_base_url": "file:///tmp"}}, "PROVIDER_URL_INVALID"),
    ("deepseek", {"api": {"deepseek_base_url": "https://user:secret@host"}}, "PROVIDER_URL_INVALID"),
])
def test_invalid_connection_is_rejected_before_network(provider, updates, code):
    probe = MagicMock()
    with pytest.raises(ProviderModelsError) as caught:
        service(probe).discover_models(provider, updates)
    assert caught.value.code == code
    probe.assert_not_called()


def test_missing_key_does_not_request_models():
    probe = MagicMock()
    svc = service(probe)
    svc.config.data["api"]["deepseek_api_key"] = ""
    with pytest.raises(ProviderModelsError) as caught:
        svc.discover_models("deepseek")
    assert caught.value.code == "PROVIDER_CREDENTIAL_MISSING"
    probe.assert_not_called()


def test_sdk_discovery_is_one_bounded_request_without_page_iteration(monkeypatch):
    factory = MagicMock()
    client = factory.return_value.__enter__.return_value
    page = MagicMock()
    page.data = [SimpleNamespace(id="actual-model")]
    page.__iter__.side_effect = AssertionError("must not auto paginate")
    client.models.list.return_value = page
    monkeypatch.setattr("openai.OpenAI", factory)
    assert SettingsService._list_openai_compatible_models("deepseek", "key", "https://host/v1") == ["actual-model"]
    factory.assert_called_once_with(api_key="key", base_url="https://host/v1", timeout=10.0, max_retries=0)
    client.models.list.assert_called_once_with()
    factory.return_value.__exit__.assert_called_once()


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
