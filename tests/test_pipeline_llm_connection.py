"""Explicit per-run LLM selection must not mutate or fall back to global A."""
from dataclasses import asdict
import importlib
import json
from unittest.mock import Mock

import pytest

from src.app.services.graph_pipeline_service import prepare_graph_profile
from src.app.services.task_service import TaskService
from src.config import config
from src.task_connection_context import resolve_task_settings


def settings():
    return {"api": {"provider": "openai", "openai_api_key": "secret-A",
        "openai_base_url": "https://a.invalid/v1", "openai_model": "model-A"},
        "external_tts": {}, "connection_profiles": {"active_llm": "A", "active_tts": "tts",
        "llm": [{"id": label, "name": label, "provider": "openai", "api_key": "secret-" + label,
                  "base_url": "https://" + label.lower() + ".invalid/v1", "model": "model-" + label}
                 for label in ("A", "B")], "tts": [{"id": "tts", "provider": "openai_compatible"}]}}


def profile(model="default", reference="B"):
    return {"version": 1, "stages": {"translate": {"enabled": True, "provider": "openai",
        "model": model, "options": {"connection_ref": reference}, "provider_options": {}}}}


def test_graph_translation_pins_selected_connection_across_retry(monkeypatch, tmp_path):
    original = settings()
    monkeypatch.setattr(config, "_config", original)
    subtitle = tmp_path / "input.vtt"
    subtitle.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nFixture.\n", encoding="utf-8")
    profile = {
        "version": 2,
        "graph": {
            "version": 2,
            "nodes": [{"id": "translator", "kind": "translate", "provider": "openai",
                       "model": "default", "source_lang": "en", "target_lang": "zh",
                       "options": {"connection_ref": "B"}}],
            "input_slots": [{"id": "source", "type": "subtitle", "label": "Source", "language": "en"}],
            "edges": [{"source": {"kind": "slot", "slot_id": "source"},
                       "target": {"node_id": "translator", "port": "subtitle"}}],
            "outputs": [{"node_id": "translator", "port": "subtitle"}],
        },
        "bindings": {"source": {"path": str(subtitle), "language": "en", "language_confirmed": True}},
    }
    prepared, _ = prepare_graph_profile(profile, declared_paths=[str(subtitle)])
    tasks = TaskService()
    spec, _ = tasks.create_task_spec(task_type="pipeline", task_source="test", session_id="test",
                                     execution_profile=prepared, graph_prepared=True)
    assert spec.execution_profile["graph"]["nodes"][0]["model"] == "model-B"
    assert profile["graph"]["nodes"][0]["model"] == "default"
    assert "secret-B" not in json.dumps(asdict(spec))
    assert config.to_dict() == original

    changed = settings()
    changed["connection_profiles"]["llm"][1]["api_key"] = "changed-B"
    monkeypatch.setattr(config, "_config", changed)
    with tasks.graph_node_connection_context(spec.task_id, "translator"):
        assert config.to_dict()["api"]["openai_api_key"] == "secret-B"
    tasks.start_task(spec.task_id)
    tasks.fail_task(spec.task_id, message="injected failure")
    retried = tasks.retry_task(spec.task_id)
    with tasks.graph_node_connection_context(retried.task_id, "translator"):
        assert config.to_dict()["api"]["openai_api_key"] == "secret-B"
    assert config.to_dict() == changed


@pytest.mark.parametrize("change", ["missing", "provider", "empty-key", "empty-ref", "null-ref"])
def test_invalid_explicit_connection_never_falls_back(change):
    data, execution = settings(), profile()
    if change == "missing":
        execution["stages"]["translate"]["options"]["connection_ref"] = "deleted"
    elif change == "provider":
        execution["stages"]["translate"]["provider"] = "deepseek"
    elif change == "empty-key":
        data["connection_profiles"]["llm"][1]["api_key"] = ""
    elif change == "null-ref":
        execution["stages"]["translate"]["options"]["connection_ref"] = None
    else:
        execution["stages"]["translate"]["options"]["connection_ref"] = ""
    with pytest.raises(ValueError):
        resolve_task_settings(data, execution)


def test_model_discovery_targets_B_without_saving_or_fallback(monkeypatch, tmp_path):
    from src.app.services.settings_service import SettingsService
    from src.app.errors import AppValidationError
    module = importlib.import_module("src.config")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(module, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = object.__new__(module.Config)
    cfg.save(settings())
    cfg.reload()
    before = module.CONFIG_FILE.read_bytes()
    probe = Mock(return_value=["model-B"])
    service = SettingsService(config_manager=cfg, model_probe=probe)
    assert service.discover_models("openai", {"active_connections": {"llm": "B"}}) == ["model-B"]
    probe.assert_called_once_with("openai", "secret-B", "https://b.invalid/v1")
    assert module.CONFIG_FILE.read_bytes() == before
    assert cfg.to_dict()["connection_profiles"]["active_llm"] == "A"
    with pytest.raises(AppValidationError):
        service.discover_models("openai", {"active_connections": {"llm": "missing"}})
    assert probe.call_count == 1
