"""Connection settings use a narrow, credential-free response and isolated storage."""
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api.http.routes.speech import router
from src.app.services.speech_service import SpeechService, get_speech_service
from src.core.speech.store import SpeechStore


@pytest.fixture
def connections_http(tmp_path):
    # These requests do not dispatch tasks or need the application's startup hooks.
    service = SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=Mock(),
                            dispatcher=Mock(), artifacts=Mock())
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_speech_service] = lambda: service
    with TestClient(app) as client:
        yield client, service


def test_connections_get_only_reads_connections_and_never_loads_credentials(connections_http, monkeypatch):
    client, service = connections_http
    saved = service.save_connection({
        "name": "Configured", "provider_id": "fish_audio", "deployment": "cloud",
        "base_url": "https://speech.invalid/v1", "api_key": "test-only-never-return",
    })
    unconfigured = service.save_connection({
        "name": "No credential", "provider_id": "fish_audio", "deployment": "cloud",
        "base_url": "https://speech.invalid/v1",
    })
    stored_list = service.store.list
    calls = []

    def connections_only(collection):
        calls.append(collection)
        assert collection == "connections", "Connection settings must not load other collections"
        return stored_list(collection)

    open_path = Path.open

    def no_credential_reads(path, *args, **kwargs):
        assert not path.is_relative_to(service.store.root / "credentials"), "Do not read credentials"
        return open_path(path, *args, **kwargs)

    monkeypatch.setattr(service.store, "list", connections_only)
    monkeypatch.setattr(Path, "open", no_credential_reads)
    monkeypatch.setattr(service, "library", Mock(side_effect=AssertionError("Do not load the library")))
    monkeypatch.setattr(service, "connection_context", Mock(side_effect=AssertionError("Do not resolve credentials")))

    response = client.get("/api/v1/speech/connections")
    assert response.status_code == 200
    assert calls == ["connections"]
    assert set(response.json()) == {"connections"}
    items = {item["id"]: item for item in response.json()["connections"]}
    assert set(items) == {saved["id"], unconfigured["id"]}
    assert items[saved["id"]]["credential_configured"] is True
    assert items[unconfigured["id"]]["credential_configured"] is False
    for item in items.values():
        assert set(item) == {"id", "name", "provider_id", "deployment", "base_url", "credential_configured"}
    assert "test-only-never-return" not in response.text
    assert "credential_ref" not in response.text


def test_connection_save_preserves_credentials_when_key_is_omitted_or_empty(connections_http):
    client, service = connections_http
    saved = service.save_connection({
        "name": "Configured", "provider_id": "fish_audio", "deployment": "cloud",
        "base_url": "https://speech.invalid/v1", "api_key": "test-only-preserved", "timeout": 77,
    })
    credential = service._credential_path(saved)
    original = credential.read_bytes()
    for patch in ({"name": "Renamed"}, {"name": "Renamed again", "api_key": ""}):
        response = client.post("/api/v1/speech/connections", json={"id": saved["id"], **patch})
        assert response.status_code == 200
        assert response.json()["credential_configured"] is True
        assert "api_key" not in response.json()
        assert "test-only-preserved" not in response.text
        stored = service.store.get("connections", saved["id"])
        assert stored["credential_ref"] == saved["credential_ref"]
        assert stored["timeout"] == 77
        assert credential.read_bytes() == original
    assert list(credential.parent.iterdir()) == [credential]
    response = client.post("/api/v1/speech/connections", json={
        "id": saved["id"], "base_url": "https://other.invalid/v1", "api_key": "",
    })
    assert response.status_code == 422
    assert service.store.get("connections", saved["id"])["base_url"] == saved["base_url"]
    assert credential.read_bytes() == original


def test_local_default_is_idempotent_without_credentials_or_runtime_start(connections_http, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    client, service = connections_http
    missing = tmp_path / "missing-runtime" / "python.exe"
    monkeypatch.setattr("src.core.runtime.profiles.get_runtime_profile_resolver",
                        lambda: SimpleNamespace(resolve=lambda _: SimpleNamespace(python_executable=missing)))
    monkeypatch.setattr(service, "connection_context", Mock(side_effect=AssertionError("No credential resolution")))
    monkeypatch.setattr("subprocess.Popen", Mock(side_effect=AssertionError("Do not start a model")))
    body = {"provider_id": "qwen3", "model": "qwen3-base", "mode": "reference"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        repeated = list(pool.map(lambda _: service.resolve_local_connection(**body), range(8)))
    response = client.post("/api/v1/speech/connections/local-default", json=body)
    assert response.status_code == 200
    result = response.json()
    assert result["readiness"]["ready"] is False
    assert result["readiness"]["verified"] is False
    assert result["readiness"]["code"] == "runtime_missing"
    assert {item["connection"]["id"] for item in repeated} == {result["connection"]["id"]}
    assert len(service.store.list("connections")) == 1
    assert result["connection"]["deployment"] == "local"
    assert not (service.store.root / "credentials").exists()
    assert not service.store.list("recipes")


@pytest.mark.parametrize("deployments", [("local",), ("local", "local"), ("cloud",)])
def test_local_default_reuses_only_unambiguous_local_choice(connections_http, monkeypatch, deployments):
    client, service = connections_http
    from src.core.speech.providers import get_provider

    probe = Mock(return_value={"ready": False, "verified": False, "detail": "Not verified"})
    monkeypatch.setattr(get_provider("qwen3"), "probe", probe)
    records = [service.store.create("connections", {"provider_id": "qwen3", "name": f"Existing {index}",
               "deployment": deployment, "model_path": "custom-model", "device": "cpu"})
               for index, deployment in enumerate(deployments)]
    before = service.store.path.read_bytes()
    response = client.post("/api/v1/speech/connections/local-default",
                           json={"provider_id": "qwen3", "model": "qwen3-base", "mode": "reference"})
    assert response.status_code == 200
    if deployments == ("local",):
        assert response.json()["connection"]["id"] == records[0]["id"]
        assert response.json()["connection"]["device"] == "cpu"
        probe.assert_called_once_with({"model_path": "custom-model", "device": "cpu",
                                       "model": "qwen3-base", "mode": "reference"})
    else:
        assert response.json()["connection"] is None
        assert response.json()["readiness"] is None
        probe.assert_not_called()
    assert service.store.path.read_bytes() == before


def test_local_default_metadata_readiness_is_not_synthesis_verification(connections_http, monkeypatch, tmp_path):
    from types import SimpleNamespace

    client, service = connections_http
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"tts_model_type":"base"}')
    (model / "model.safetensors").write_bytes(b"metadata-test-not-real-weights")
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"metadata-test-not-an-executable")
    monkeypatch.setattr("src.core.runtime.profiles.get_runtime_profile_resolver",
                        lambda: SimpleNamespace(resolve=lambda _: SimpleNamespace(python_executable=executable)))
    monkeypatch.setattr("src.core.resources.model_reference.resolve_model_reference", lambda _: str(model))
    monkeypatch.setattr("subprocess.Popen", Mock(side_effect=AssertionError("Do not start a model")))
    body = {"provider_id": "qwen3", "model": "qwen3-base", "mode": "reference"}
    result = client.post("/api/v1/speech/connections/local-default", json=body).json()
    assert result["readiness"]["ready"] is True
    assert result["readiness"]["verified"] is False
    assert "尚未验证依赖或执行合成" in result["readiness"]["detail"]
    (model / "model.safetensors").unlink()
    result = client.post("/api/v1/speech/connections/local-default", json=body).json()
    assert result["readiness"]["ready"] is False
    assert result["readiness"]["code"] == "model_missing"
    for provider in ("fish_audio", "edge"):
        rejected = client.post("/api/v1/speech/connections/local-default", json={**body, "provider_id": provider})
        assert rejected.status_code == 422
    assert len(service.store.list("connections")) == 1
