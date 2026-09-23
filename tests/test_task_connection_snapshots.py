"""Connection changes must not retarget queued or retried paid work."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import threading

import pytest

from src.config import config
from src.app.errors import AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services.task_service import TaskService
from src.core.tasks import TaskDispatcher
from src.task_connection_context import connection_context, overlay_connections


def _settings(label):
    return {
        "api": {"deepseek_api_key": f"secret-{label}", "deepseek_base_url": f"https://{label}.example"},
        "external_tts": {"api_key": f"tts-secret-{label}", "base_url": f"https://tts-{label}.example"},
        "paths": {"output_dir": label},
    }


def _create(service):
    return service.create_task_spec(task_type="pipeline", task_source="test", session_id="test")[0]


def test_queued_task_keeps_connections_but_unrelated_settings_stay_live(monkeypatch):
    monkeypatch.setattr(config, "_config", _settings("first"))
    service = TaskService()
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    spec = _create(service)
    monkeypatch.setattr(config, "_config", _settings("second"))
    dispatcher.register_executor("pipeline", lambda spec: config.to_dict())
    result = dispatcher.run(spec.task_id)
    assert result["api"] == _settings("first")["api"]
    assert result["external_tts"] == _settings("first")["external_tts"]
    assert result["paths"] == _settings("second")["paths"]
    assert config.get("api.deepseek_api_key") == "secret-second"


def test_retry_keeps_original_connections_and_context_resets_after_failure(monkeypatch):
    monkeypatch.setattr(config, "_config", _settings("first"))
    service = TaskService()
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    spec = _create(service)

    def fail(spec):
        assert config.get("api.deepseek_api_key") == "secret-first"
        raise RuntimeError("temporary failure")

    dispatcher.register_executor("pipeline", fail)
    monkeypatch.setattr(config, "_config", _settings("second"))
    with pytest.raises(RuntimeError, match="temporary failure"):
        dispatcher.run(spec.task_id)
    assert config.get("api.deepseek_api_key") == "secret-second"
    retry = service.retry_task(spec.task_id)
    dispatcher.register_executor("pipeline", lambda spec: config.get("external_tts.api_key"))
    assert dispatcher.run(retry.task_id) == "tts-secret-first"


def test_parallel_running_tasks_do_not_share_or_leak_connections(monkeypatch):
    monkeypatch.setattr(config, "_config", _settings("first"))
    service = TaskService()
    first = _create(service)
    monkeypatch.setattr(config, "_config", _settings("second"))
    second = _create(service)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    barrier = threading.Barrier(2)

    def execute(spec):
        before = config.get("api.deepseek_api_key")
        barrier.wait(timeout=5)
        assert config.get("api.deepseek_api_key") == before
        return before

    dispatcher.register_executor("pipeline", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(dispatcher.run, [first.task_id, second.task_id]))
    assert results == ["secret-first", "secret-second"]
    assert config.get("api.deepseek_api_key") == "secret-second"


def test_snapshot_secrets_are_absent_from_public_and_persisted_task(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_config", _settings("first"))
    store = SqliteStateStore(tmp_path / "state.db")
    service = TaskService(state_store=store)
    spec = _create(service)
    service.start_task(spec.task_id)
    service.complete_task(spec.task_id)
    public = json.dumps([asdict(service.get_task_spec(spec.task_id)), asdict(service.get_task(spec.task_id))])
    persisted = repr(store.load_terminal_tasks())
    for value in (public, persisted):
        assert "secret-first" not in value
        assert "https://first.example" not in value
    restored = TaskService(state_store=store)
    with pytest.raises(AppValidationError, match="historical tasks"):
        restored.retry_task(spec.task_id)


def test_missing_section_and_nested_context_do_not_fall_back_or_mutate():
    current = _settings("current")
    with connection_context({"api": {}, "external_tts": {}}):
        assert overlay_connections(current)["external_tts"] == {}
        with connection_context({"api": {"key": "nested"}}):
            view = overlay_connections(current)
            view["api"]["key"] = "mutated"
            assert overlay_connections(current)["api"]["key"] == "nested"
        assert overlay_connections(current)["api"] == {}
    assert overlay_connections(current) == current


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_empty_explicit_translator_key_does_not_use_another_profile(monkeypatch, provider):
    from src.core.engines.llm.translator import Translator

    monkeypatch.setattr(config, "_config", {"api": {f"{provider}_api_key": "other-profile-secret"}})
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "environment-secret")
    translator = Translator(provider=provider, api_key="", use_terminology=False)
    assert translator.api_key == ""
    with pytest.raises(ValueError, match="API"):
        translator.get_client()


@pytest.mark.parametrize("provider", ["deepseek", "openai"])
def test_translator_uses_effective_config_without_independent_env_fallback(monkeypatch, provider):
    from src.core.engines.llm.translator import Translator

    monkeypatch.setattr(config, "_config", {"api": {f"{provider}_api_key": ""}})
    monkeypatch.setenv(f"{provider.upper()}_API_KEY", "unrelated-environment-secret")
    translator = Translator(provider=provider, use_terminology=False)
    assert translator.api_key == ""
    monkeypatch.setattr(config, "_config", {"api": {f"{provider}_api_key": "effective-secret"}})
    assert translator.api_key == "effective-secret"
