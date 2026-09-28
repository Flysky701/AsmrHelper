"""Explicit per-run LLM selection must not mutate or fall back to global A."""
from copy import deepcopy
from dataclasses import asdict
import importlib
import json
from unittest.mock import Mock

import pytest

from src.config import config
from src.task_connection_context import resolve_task_settings
from src.app.services.task_service import TaskService
from src.core.tasks import TaskDispatcher
from src.recovery_connections import restore_recovery_connections


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


def test_task_and_retry_pin_B_even_when_global_A_and_same_provider(monkeypatch):
    original = settings()
    monkeypatch.setattr(config, "_config", original)
    tasks = TaskService()
    spec, _ = tasks.create_task_spec(task_type="pipeline", task_source="test", session_id="test", execution_profile=profile())
    assert original == settings()
    record = tasks._connection_records[spec.task_id]
    assert record["selected"]["llm"] == "B"
    assert restore_recovery_connections(record, original)["api"]["openai_api_key"] == "secret-B"
    dispatcher = TaskDispatcher(tasks.registry, task_service=tasks)
    def fail(spec):
        assert config.to_dict()["api"]["openai_base_url"] == "https://b.invalid/v1"
        assert config.to_dict()["api"]["openai_api_key"] == "secret-B"
        raise RuntimeError("planned")
    dispatcher.register_executor("pipeline", fail)
    changed = settings()
    changed["connection_profiles"]["llm"][1]["api_key"] = "changed-B"
    monkeypatch.setattr(config, "_config", changed)
    with pytest.raises(RuntimeError, match="planned"):
        dispatcher.run(spec.task_id)
    retried = tasks.retry_task(spec.task_id)
    dispatcher.register_executor("pipeline", lambda spec: config.to_dict()["api"]["openai_api_key"])
    assert dispatcher.run(retried.task_id) == "secret-B"
    assert config.to_dict()["connection_profiles"]["active_llm"] == "A"
    serialized = json.dumps([asdict(spec), record])
    assert "secret-A" not in serialized and "secret-B" not in serialized


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


def test_pipeline_default_model_resolves_B_before_submission(monkeypatch):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService
    monkeypatch.setattr(config, "_config", settings())
    tasks, catalog = Mock(), Mock()
    tasks.create_task_spec.return_value = (Mock(task_id="test"), Mock())
    catalog.inspect_paths.return_value = [Mock(asset_id="input", absolute_path="input.wav")]
    pipeline = PipelineService(task_service=tasks, resource_service=Mock(), workspace_service=Mock(),
        input_catalog_service=catalog, session_service=Mock(), artifact_service=Mock(), executor=Mock())
    source = profile()
    pipeline.create_pipeline_task_spec(PipelineRequest(input_path="input.wav", execution_profile=source))
    captured = tasks.create_task_spec.call_args.kwargs["execution_profile"]
    assert captured["stages"]["translate"]["model"] == "model-B"
    assert source["stages"]["translate"]["model"] == "default"
    assert config.to_dict() == settings()


def test_readiness_validates_selected_connection_not_global_model_status(monkeypatch, tmp_path):
    from src.app.services.resource_service import ResourceService
    monkeypatch.setattr(config, "_config", settings())
    models, descriptors = Mock(), Mock()
    models.list_models.return_value = []
    descriptors.get_descriptor.return_value = {"runtime_requirements": {}, "supported_models": [], "default_model": "model-A"}
    resources = ResourceService(project_root=tmp_path, model_service=models, descriptor_service=descriptors)
    assert resources._check_pipeline_profile(profile()) == []
    models.get_model_status.assert_not_called()
    data = settings()
    data["connection_profiles"]["llm"][1]["api_key"] = ""
    monkeypatch.setattr(config, "_config", data)
    issues = resources._check_pipeline_profile(profile())
    assert issues[0]["code"] == "LLM_CONNECTION_NOT_READY"


def test_batch_freezes_B_for_delayed_children_and_retry(monkeypatch, tmp_path):
    from src.app.services.batch_run_service import BatchRunService
    monkeypatch.setattr(config, "_config", settings())
    orchestrator = Mock()
    batch = BatchRunService(pipeline_orchestrator=orchestrator)
    monkeypatch.setattr(batch, "_start_monitor_locked", lambda batch_id: None)
    source = tmp_path / "input.wav"
    source.write_bytes(b"fixture")
    record = batch.create_batch(name="test", inputs=[{"path": str(source)}], output_dir="", execution_profile=profile())
    assert record.execution_profile["stages"]["translate"]["model"] == "model-B"
    assert "secret-B" not in json.dumps(asdict(record))
    changed = settings()
    changed["connection_profiles"]["llm"][1]["api_key"] = "changed"
    monkeypatch.setattr(config, "_config", changed)
    observed = []
    def submit(request, **kwargs):
        effective = resolve_task_settings(config.to_dict(), request.execution_profile)
        observed.append(effective["api"]["openai_api_key"])
        return Mock(task_id="task", state="failed", progress=1, message="failed", error=None)
    orchestrator.submit_task.side_effect = submit
    live = batch._batches[record.batch_id]
    batch._launch_item_locked(live, live.items[0])
    batch.retry_failed(record.batch_id)
    batch._launch_item_locked(live, live.items[0])
    assert observed == ["secret-B", "secret-B"]
    assert config.to_dict() == changed
    # A restarted process may restore unchanged credentials, never changed ones.
    batch._llm_snapshots.clear()
    batch._launch_item_locked(live, live.items[0])
    assert live.items[0].state == "failed" and len(observed) == 2


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
