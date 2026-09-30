"""Fish voice lookup: mocked HTTP only, no credentials or synthesis services."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.speech import providers
from src.api.http.routes.speech import router
from src.app.services.speech_service import get_speech_service


def context(base="https://api.fish.audio/v1"):
    return {"connection": {"provider_id": "fish_audio", "base_url": base,
                           "api_key": "test-only-not-a-real-key"}}


@pytest.fixture
def upstream(monkeypatch):
    requests = []
    state = {"status": 200, "body": {"items": [], "has_more": False}}

    def handle(request):
        requests.append(request)
        if state.get("exception"):
            raise state["exception"]("controlled failure", request=request)
        if "text" in state:
            return httpx.Response(state["status"], text=state["text"])
        return httpx.Response(state["status"], json=state["body"])

    real_client = httpx.Client
    monkeypatch.setattr(providers, "httpx", SimpleNamespace(
        Client=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
        Timeout=httpx.Timeout, TimeoutException=httpx.TimeoutException,
        RequestError=httpx.RequestError,
    ))
    return state, requests


@pytest.mark.parametrize("base,expected", [
    ("https://api.fish.audio/v1", "https://api.fish.audio/model"),
    ("https://api.fish.audio/v1/tts", "https://api.fish.audio/model"),
    ("https://api.fish.audio", "https://api.fish.audio/model"),
    ("http://proxy.test/fish/v1/tts", "http://proxy.test/fish/v1/model"),
])
def test_lookup_maps_real_ids_and_keeps_proxy_prefix(upstream, base, expected):
    state, requests = upstream
    state["body"] = {"items": [{"_id": "voice-1", "title": "温柔声音"}], "has_more": True}
    result = providers.get_provider("fish_audio").list_hosted_voices(
        context(base), title=" 温柔 ", page=2, page_size=20, workspace_only=True)
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?")[0] == expected
    assert dict(request.url.params) == {"title": "温柔", "page_number": "2", "page_size": "20", "self": "true"}
    assert result["items"] == [{"id": "voice-1", "name": "温柔声音"}]
    assert result["page"] == 2 and result["has_more"]
    assert "test-only" not in str(result)


def test_public_empty_and_window_pagination(upstream):
    state, requests = upstream
    provider = providers.get_provider("fish_audio")
    assert provider.list_hosted_voices(context(), workspace_only=False)["items"] == []
    assert requests[-1].url.params["self"] == "false"
    state["body"] = {"items": [{"_id": "id", "title": "Name"}], "total": 999,
                     "has_more": False, "window_limited": True}
    result = provider.list_hosted_voices(context())
    assert not result["has_more"] and result["notice"]
    state["body"] = {"items": [{"_id": "id", "title": "Name"}], "total": 30}
    assert provider.list_hosted_voices(context())["has_more"]


@pytest.mark.parametrize("status,code", [
    (401, "voice_catalog_unauthorized"), (403, "voice_catalog_unauthorized"),
    (404, "voice_catalog_unsupported"), (405, "voice_catalog_unsupported"),
    (302, "voice_catalog_unsupported"), (429, "voice_catalog_rate_limited"),
    (500, "voice_catalog_failed"),
])
def test_remote_errors_are_safe_manual_fallbacks(upstream, status, code):
    state, requests = upstream
    state.update(status=status, text="sensitive upstream error body")
    with pytest.raises(providers.ProviderError) as error:
        providers.get_provider("fish_audio").list_hosted_voices(context())
    assert error.value.code == code
    assert "Voice ID" in str(error.value)
    assert "sensitive" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("failure,code", [
    (httpx.ReadTimeout, "voice_catalog_timeout"),
    (httpx.ConnectError, "voice_catalog_network"),
])
def test_network_failures(upstream, failure, code):
    upstream[0]["exception"] = failure
    with pytest.raises(providers.ProviderError) as error:
        providers.get_provider("fish_audio").list_hosted_voices(context())
    assert error.value.code == code


@pytest.mark.parametrize("body", [[], {}, {"items": "bad"}, {"items": [{"_id": ""}]}])
def test_invalid_payload_does_not_produce_invented_ids(upstream, body):
    upstream[0]["body"] = body
    with pytest.raises(providers.ProviderError, match="手填 Voice ID"):
        providers.get_provider("fish_audio").list_hosted_voices(context())


def test_http_route_uses_selected_connection_and_validates_pagination(upstream):
    seen = []
    connection = context()["connection"]

    def get_connection(kind, identifier):
        seen.append((kind, identifier))
        if identifier != "chosen":
            raise KeyError("连接不存在")
        return connection

    service = SimpleNamespace(store=SimpleNamespace(get=get_connection),
                              connection_context=lambda item: {"connection": item})
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_speech_service] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/v1/speech/connections/chosen/voices?title=hello&page=2&workspace_only=false")
        assert response.status_code == 200
        assert seen == [("connections", "chosen")]
        assert upstream[1][-1].url.params["self"] == "false"
        assert client.get("/api/v1/speech/connections/chosen/voices?page=0").status_code == 422
        assert client.get("/api/v1/speech/connections/chosen/voices?page_size=101").status_code == 422
        assert client.get("/api/v1/speech/connections/missing/voices").status_code == 422
        connection["provider_id"] = "openai_compatible"
        assert client.get("/api/v1/speech/connections/chosen/voices").status_code == 422
    assert len(upstream[1]) == 1
