"""Tests for application-layer services — current API contracts.

Covers TaskService, ResourceService, SubtitleService, and PipelineService
with their current interfaces.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _FakeConfig:
    def __init__(self):
        self.data = {
            "api": {
                "provider": "deepseek",
                "deepseek_api_key": "secret-deepseek",
                "openai_api_key": "",
                "deepseek_base_url": "https://api.deepseek.com",
                "openai_base_url": "https://api.openai.com/v1",
            },
            "tts": {"engine": "edge", "voice": "voice", "speed": 1.0},
            "paths": {"output_dir": "", "vtt_dir": "", "model_cache_dir": "", "temp_dir": ""},
            "processing": {
                "original_volume": 0.85,
                "tts_volume": 0.5,
                "tts_delay": 0,
                "vocal_model": "htdemucs",
                "asr_model": "faster-whisper-base",
            },
        }
        self.persisted = None

    @staticmethod
    def _merge(base, updates):
        for key, value in updates.items():
            if isinstance(base.get(key), dict) and isinstance(value, dict):
                _FakeConfig._merge(base[key], value)
            else:
                base[key] = deepcopy(value)

    def to_dict(self):
        return deepcopy(self.data)

    def build_effective_config(self, config_override=None):
        candidate = self.to_dict()
        self._merge(candidate, config_override or {})
        return candidate

    def validate(self, candidate):
        return True, []

    def persist_updates(self, updates):
        self.persisted = deepcopy(updates)
        self._merge(self.data, updates)


class TestSettingsService:
    def test_public_view_never_returns_secret_or_placeholder(self):
        from src.app.services.settings_service import SettingsService

        service = SettingsService(config_manager=_FakeConfig())

        settings = service.get_settings()

        assert "api" not in settings
        assert settings["providers"]["deepseek"]["credential_configured"] is True
        assert "credential" not in settings["providers"]["deepseek"]
        assert "secret-deepseek" not in repr(settings)
        assert "***configured***" not in repr(settings)

    def test_empty_credential_write_preserves_existing_secret(self):
        from src.app.services.settings_service import SettingsService

        fake_config = _FakeConfig()
        service = SettingsService(config_manager=fake_config)

        service.update_settings(
            {
                "providers": {
                    "default_llm": "deepseek",
                    "deepseek": {
                        "base_url": "https://example.invalid/v1",
                        "credential": "",
                    },
                }
            }
        )

        assert fake_config.data["api"]["deepseek_api_key"] == "secret-deepseek"
        assert "deepseek_api_key" not in fake_config.persisted["api"]
        assert fake_config.data["api"]["deepseek_base_url"] == "https://example.invalid/v1"

    def test_provider_test_performs_probe_with_candidate_settings(self):
        from src.app.services.settings_service import SettingsService

        probe = MagicMock()
        service = SettingsService(config_manager=_FakeConfig(), provider_probe=probe)

        result = service.test_provider(
            "openai",
            {
                "providers": {
                    "openai": {
                        "credential": "candidate-key",
                        "base_url": "https://gateway.invalid/v1",
                    }
                }
            },
        )

        assert result.success is True
        probe.assert_called_once_with(
            "openai",
            "candidate-key",
            "https://gateway.invalid/v1",
        )

    def test_provider_test_reports_stable_failure_code(self):
        from src.app.services.settings_service import SettingsService

        probe = MagicMock(side_effect=RuntimeError("authentication failed"))
        service = SettingsService(config_manager=_FakeConfig(), provider_probe=probe)

        result = service.test_provider("deepseek")

        assert result.success is False
        assert result.error_code == "PROVIDER_CONNECTION_FAILED"
        assert "authentication failed" in result.message

    def test_update_settings_reports_persistence_failure(self):
        from src.app.errors import AppExecutionError
        from src.app.services.settings_service import SettingsService

        class FailingConfig(_FakeConfig):
            def persist_updates(self, updates):
                raise PermissionError("configuration is read-only")

        service = SettingsService(config_manager=FailingConfig())

        with pytest.raises(AppExecutionError, match="configuration is read-only"):
            service.update_settings({"tts": {"speed": 1.25}})


def test_config_save_is_atomic_and_propagates_replace_failure(tmp_path, monkeypatch):
    import src.config as config_module

    manager = object.__new__(config_module.Config)
    manager._config = {"api": {"provider": "deepseek"}}
    target = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)

    def fail_replace(_source, _target):
        raise PermissionError("replace denied")

    monkeypatch.setattr(config_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="保存配置失败"):
        manager.save()

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_config_partial_updates_are_serialized(tmp_path, monkeypatch):
    import src.config as config_module

    manager = object.__new__(config_module.Config)
    manager._config = manager._default_config()
    target = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_FILE", target)
    manager.save(config_data={})
    original_save = manager.save

    def slow_save(config_data=None):
        time.sleep(0.03)
        original_save(config_data=config_data)

    monkeypatch.setattr(manager, "save", slow_save)
    gate = threading.Barrier(3)

    def update(payload):
        gate.wait()
        manager.persist_updates(payload)

    first = threading.Thread(target=update, args=({"tts": {"speed": 1.25}},))
    second = threading.Thread(
        target=update,
        args=({"processing": {"original_volume": 0.6}},),
    )
    first.start()
    second.start()
    gate.wait()
    first.join(timeout=2)
    second.join(timeout=2)

    persisted = manager.get_file_config()
    assert persisted["tts"]["speed"] == 1.25
    assert persisted["processing"]["original_volume"] == 0.6


class TestArtifactResultContract:
    def test_result_has_one_authoritative_primary_artifact(self):
        from src.app.services.artifact_service import ArtifactService

        service = ArtifactService()
        secondary = service.register_artifact(
            task_id="task-result",
            artifact_type="text.transcript",
            path="C:/output/transcript.txt",
            preview_kind="text",
        )
        primary = service.register_artifact(
            task_id="task-result",
            artifact_type="audio.mix",
            path="C:/output/final.wav",
            preview_kind="audio",
            is_primary=True,
        )

        result = service.get_task_result_view("task-result")

        assert set(result) == {
            "task_id",
            "primary_artifact_id",
            "artifacts",
            "warnings",
        }
        assert result["primary_artifact_id"] == primary.artifact_id
        assert [entry.artifact_id for entry in result["artifacts"]] == [
            secondary.artifact_id,
            primary.artifact_id,
        ]

    def test_first_artifact_is_primary_fallback_without_path_guessing(self):
        from src.app.services.artifact_service import ArtifactService

        service = ArtifactService()
        first = service.register_artifact(
            task_id="task-fallback",
            artifact_type="subtitle.srt",
            path="C:/output/unusual-name.data",
            preview_kind="subtitle",
        )

        result = service.get_task_result_view("task-fallback")

        assert result["primary_artifact_id"] == first.artifact_id


class TestCapabilityOptionContract:
    def test_provider_options_expose_stable_ui_constraints(self):
        from src.app.services.capability_descriptor_service import (
            CapabilityDescriptorService,
        )

        descriptor = CapabilityDescriptorService().get_descriptor("asr", "faster_whisper")
        option = descriptor["provider_option_schema"][0]

        assert set(option) == {
            "name",
            "type",
            "required",
            "default",
            "description",
            "enum",
            "min",
            "max",
            "advanced",
            "secret",
        }
        assert option["advanced"] is True
        assert option["secret"] is False

    def test_llm_capability_models_come_from_runtime_registry(self):
        from src.app.services.capability_descriptor_service import (
            CapabilityDescriptorService,
        )
        from src.core.engines.llm import get_llm_registry
        from src.core.engines.llm.registry import LLM_SUPPORTED_MODELS
        from src.core.engines.llm.translator import Translator

        registry = get_llm_registry()
        descriptor = CapabilityDescriptorService().get_descriptor("llm", "deepseek")

        assert descriptor["default_model"] == registry.default_model("deepseek")
        assert descriptor["default_model"] == "deepseek-chat"
        assert descriptor["supported_models"] == registry.list_models("deepseek")
        assert Translator.MODELS is LLM_SUPPORTED_MODELS


class TestModelService:
    def test_list_models_normalizes_missing_install_strategy(self):
        from src.app.services.model_service import ModelService

        core_service = MagicMock()
        core_service.list_models.return_value = [
            SimpleNamespace(
                id="deepseek",
                kind="cloud",
                category="llm",
                provider="deepseek",
                engine=None,
                display_name="DeepSeek API",
                install_strategy=None,
                capability_models=[],
                supports_install=False,
                supports_remove=False,
                family_id=None,
                variant_group=None,
                variant_tier=None,
                is_primary_variant=False,
                dependency_group=None,
                runtime_profile=None,
                preferred_runtime=None,
                install_modes=[],
                default_install_mode=None,
                required_assets=[],
                recommended_assets=[],
                required_system_tools=[],
                supported_os=[],
            )
        ]

        models = ModelService(core_service=core_service).list_models()

        assert models[0].install_strategy == ""

    def test_async_install_fails_task_when_core_install_returns_false(self):
        from src.app.services.model_service import ModelService
        from src.app.services.task_service import TaskService

        task_service = TaskService()
        core_service = MagicMock()
        core_service.get_model.return_value = SimpleNamespace(kind="local")
        core_service.install.return_value = False
        service = ModelService(core_service=core_service, task_service=task_service)

        accepted = service.install_model_async("optional-model")

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if task_service.get_task(accepted.task_id).state == "failed":
                break
            time.sleep(0.01)
        task = task_service.get_task(accepted.task_id)
        assert task.state == "failed"
        assert task.stage == "install"
        assert task.error["code"] == "TASK_EXECUTION_FAILED"


class TestTaskService:
    """Test TaskService lifecycle and concurrency."""

    class _FailingStateStore:
        def __init__(self, *, fail_state: str):
            self.fail_state = fail_state

        def purge_unfinished(self):
            return None

        def load_terminal_tasks(self):
            return []

        def save_task(self, task_spec, task_status):
            if task_status.state == self.fail_state:
                raise OSError("disk full")

    def test_create_persistence_failure_discards_uncommitted_task(self):
        from src.app.errors import AppExecutionError
        from src.app.services.task_service import TaskService

        service = TaskService(state_store=self._FailingStateStore(fail_state="pending"))

        with pytest.raises(AppExecutionError, match="failed to persist task creation"):
            service.create_task_spec(
                task_type="pipeline",
                task_source="test",
                session_id="session-1",
            )

        assert service.list_tasks() == []

    def test_state_persistence_failure_quarantines_task_as_failed(self):
        from src.app.errors import AppExecutionError
        from src.app.services.task_service import TaskService

        service = TaskService(state_store=self._FailingStateStore(fail_state="running"))
        spec, _ = service.create_task_spec(
            task_type="pipeline",
            task_source="test",
            session_id="session-1",
        )
        with pytest.raises(AppExecutionError, match="failed to persist task state"):
            service.start_task(spec.task_id)

        task = service.get_task(spec.task_id)
        assert task.state == "failed"
        assert task.error is not None
        assert task.error["code"] == "TASK_STATE_PERSISTENCE_FAILED"
        assert service.list_tasks(state="pending") == []

    def test_running_persistence_failure_releases_concurrency_slot(self):
        from src.app.errors import AppExecutionError
        from src.app.services.task_service import TaskService

        store = self._FailingStateStore(fail_state="never")
        service = TaskService(max_concurrent=1, state_store=store)
        spec, _ = service.create_task_spec(
            task_type="pipeline",
            task_source="test",
            session_id="session-1",
        )
        service.start_task(spec.task_id)
        store.fail_state = "running"

        with pytest.raises(AppExecutionError, match="failed to persist task state"):
            service.update_progress(spec.task_id, 0.5)

        assert service.get_task(spec.task_id).state == "failed"
        assert service.running_count() == 0

    def test_create_task_spec_and_lifecycle(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, status = service.create_task_spec(
            task_type="pipeline",
            task_source="test",
            session_id="session-1",
            input_asset_id="asset-1",
        )

        assert spec.task_id
        assert spec.task_type == "pipeline"
        assert status.state == "pending"
        assert status.stage is None
        assert status.created_at
        assert status.queued_at == status.created_at

        started = service.start_task(spec.task_id, message="running")
        assert started.state == "running"
        assert started.stage == "prepare"
        assert started.started_at

        updated = service.update_progress(
            spec.task_id, progress=0.5, message="halfway", stage="asr"
        )
        assert updated.progress == 0.5
        assert updated.stage == "asr"

        completed = service.complete_task(
            spec.task_id,
            message="done",
            detail="output.wav",
            stage="export",
            artifact_set_id=spec.task_id,
        )
        assert completed.state == "completed"
        assert completed.progress == 1.0
        assert completed.stage == "export"
        assert completed.finished_at
        assert completed.artifact_set_id == spec.task_id

    def test_runtime_events_are_incremental_and_derived_from_lifecycle(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="pipeline",
            task_source="test",
            session_id="session-1",
        )
        service.start_task(spec.task_id, message="running", stage="prepare")
        service.update_progress(
            spec.task_id,
            progress=0.4,
            message="recognizing",
            stage="asr",
        )
        service.complete_task(spec.task_id, message="done", stage="export")

        events = service.list_events(spec.task_id)

        assert [event.sequence for event in events] == [1, 2, 3, 4]
        assert [event.type for event in events] == [
            "task_created",
            "task_started",
            "stage_started",
            "task_completed",
        ]
        assert events[2].stage == "asr"
        assert events[2].data["progress"] == 0.4
        assert [
            event.sequence
            for event in service.list_events(spec.task_id, after_sequence=2)
        ] == [3, 4]

    def test_model_install_lifecycle_uses_model_operation_events(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="model_install",
            task_source="test",
            session_id="",
            execution_profile={
                "operation": "install",
                "model_id": "faster-whisper-base",
            },
        )
        service.start_task(spec.task_id, message="installing")
        service.update_progress(spec.task_id, 0.5, "downloading")
        service.complete_task(spec.task_id, "installed")

        events = service.list_events(spec.task_id)

        assert events[0].type == "task_created"
        assert all(event.type == "model_operation" for event in events[1:])
        assert events[2].data == {
            "state": "running",
            "progress": 0.5,
            "operation": "install",
            "model_id": "faster-whisper-base",
        }

    def test_fail_task(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="tool.separate", task_source="test", session_id="s1",
        )
        service.start_task(spec.task_id)
        failed = service.fail_task(spec.task_id, message="error", detail="OOM")
        assert failed.state == "failed"
        assert failed.error == {
            "code": "TASK_FAILED",
            "stage": "prepare",
            "message": "error",
            "retryable": True,
            "detail": "OOM",
        }

    def test_cancel_task(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1",
        )
        cancelled = service.cancel_task(spec.task_id)
        assert cancelled.state == "cancelled"

    def test_retry_clears_previous_runtime_state(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        service.start_task(spec.task_id, stage="asr")
        service.fail_task(spec.task_id, message="error", detail="OOM")

        retried = service.retry_task(spec.task_id)

        assert retried.state == "pending"
        assert retried.stage is None
        assert retried.error is None
        assert retried.started_at is None
        assert retried.finished_at is None

    def test_get_unknown_task_raises(self):
        from src.app.errors import AppValidationError
        from src.app.services.task_service import TaskService

        service = TaskService()
        with pytest.raises(AppValidationError):
            service.get_task("nonexistent-id")

    def test_singleton_reuses_instance(self, monkeypatch):
        import src.app.services.task_service as mod
        monkeypatch.setattr(mod, "_service", None)

        from src.app.services.task_service import get_task_service
        first = get_task_service()
        second = get_task_service()
        assert first is second

    def test_concurrent_create_is_safe(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        ids = []
        lock = threading.Lock()

        def worker():
            spec, _ = service.create_task_spec(
                task_type="pipeline", task_source="test", session_id="s1",
            )
            with lock:
                ids.append(spec.task_id)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ids) == 20
        assert len(set(ids)) == 20


class TestPipelineTaskOrchestrator:
    def test_submit_returns_before_background_pipeline_finishes(self):
        from src.app.dto import PipelineRequest
        from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
        from src.app.services.task_service import TaskService

        task_service = TaskService()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class BlockingPipelineService:
            def create_pipeline_task(self, request, *, task_source):
                spec, task = task_service.create_task_spec(
                    task_type="pipeline",
                    task_source=task_source,
                    session_id="session-1",
                    input_asset_id="asset-1",
                    execution_profile={},
                )
                return task, spec

            def run_pipeline_task(self, task_id, *, cancel_event=None):
                started.set()
                release.wait(timeout=2)
                if cancel_event is not None and cancel_event.is_set():
                    task_service.cancel_task(task_id)
                else:
                    task_service.complete_task(task_id)
                finished.set()
                return MagicMock(task_id=task_id)

        service = PipelineTaskOrchestrator(
            pipeline_service=BlockingPipelineService(),
            task_service=task_service,
            artifact_service=MagicMock(),
        )

        accepted = service.submit_task(PipelineRequest(input_path="/tmp/input.wav"))

        assert accepted.state == "pending"
        assert started.wait(timeout=1)
        assert not finished.is_set()
        assert task_service.get_task(accepted.task_id).state == "running"

        release.set()
        assert finished.wait(timeout=1)
        assert task_service.get_task(accepted.task_id).state == "completed"

    def test_cancel_is_requested_before_task_becomes_cancelled(self):
        from src.app.dto import PipelineRequest
        from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
        from src.app.services.task_service import TaskService

        task_service = TaskService()
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class CancellablePipelineService:
            def create_pipeline_task(self, request, *, task_source):
                spec, task = task_service.create_task_spec(
                    task_type="pipeline",
                    task_source=task_source,
                    session_id="session-1",
                    input_asset_id="asset-1",
                    execution_profile={},
                )
                return task, spec

            def run_pipeline_task(self, task_id, *, cancel_event=None):
                started.set()
                release.wait(timeout=2)
                if cancel_event is not None and cancel_event.is_set():
                    task_service.cancel_task(task_id)
                finished.set()
                return MagicMock(task_id=task_id)

        service = PipelineTaskOrchestrator(
            pipeline_service=CancellablePipelineService(),
            task_service=task_service,
            artifact_service=MagicMock(),
        )
        accepted = service.submit_task(PipelineRequest(input_path="/tmp/input.wav"))
        assert started.wait(timeout=1)

        cancelling = service.request_cancel(accepted.task_id)

        assert cancelling.state == "running"
        assert cancelling.message == "cancellation requested"
        release.set()
        assert finished.wait(timeout=1)
        assert task_service.get_task(accepted.task_id).state == "cancelled"

class TestResourceService:
    """Test ResourceService workspace management."""

    def test_ensure_workspace(self, tmp_path, monkeypatch):
        from src.app.services.resource_service import ResourceService
        monkeypatch.delenv("ASMR_HELPER_MODEL_ROOT", raising=False)

        service = ResourceService(project_root=tmp_path)
        workspace = service.ensure_workspace()

        assert workspace["project_root"] == tmp_path
        assert workspace["output_dir"].is_dir()
        assert workspace["models_dir"].is_dir()

    def test_check_required_resources(self, tmp_path, monkeypatch):
        from src.app.services.resource_service import ResourceService
        monkeypatch.delenv("ASMR_HELPER_MODEL_ROOT", raising=False)

        service = ResourceService(project_root=tmp_path)
        statuses = {s.name: s for s in service.check_required_resources()}

        assert statuses["project_root"].available is True
        assert statuses["output_dir"].available is True

    def test_pipeline_readiness_reports_selected_model_runtime_issue(self, tmp_path):
        from src.app.dto import ModelStatusIssueView, ModelStatusView, ModelSummary
        from src.app.services.resource_service import ResourceService

        descriptors = MagicMock()
        descriptors.get_descriptor.return_value = {
            "supported_models": ["faster-whisper-base"],
            "default_model": "faster-whisper-base",
        }
        models = MagicMock()
        models.list_models.return_value = [
            ModelSummary(
                model_id="faster-whisper-base",
                kind="local",
                category="asr",
                backend="faster_whisper",
                display_name="faster-whisper base",
            )
        ]
        models.get_model_status.return_value = ModelStatusView(
            model_id="faster-whisper-base",
            status="installed",
            detail="runtime unavailable",
            executable=False,
            issues=[
                ModelStatusIssueView(
                    code="PYTHON_DEPENDENCY_MISSING",
                    requirement="faster_whisper",
                    message="Python dependency is unavailable: faster_whisper",
                )
            ],
        )
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=descriptors,
            model_service=models,
        )

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={
                "stages": {
                    "asr": {
                        "enabled": True,
                        "provider": "faster_whisper",
                        "model": "faster-whisper-base",
                    }
                }
            },
        )

        assert result["ready"] is False
        assert result["missing_requirements"] == ["faster_whisper"]
        assert result["issues"][0]["stage"] == "asr"
        assert result["issues"][0]["action"] == "engines"

    def test_pipeline_readiness_resolves_explicit_capability_model_mapping(self, tmp_path):
        from src.app.dto import ModelStatusView, ModelSummary
        from src.app.services.resource_service import ResourceService

        descriptors = MagicMock()
        descriptors.get_descriptor.return_value = {
            "supported_models": ["htdemucs"],
            "default_model": "htdemucs",
            "runtime_requirements": {
                "python_modules": [],
                "system_tools": [],
            },
        }
        models = MagicMock()
        models.list_models.return_value = [
            ModelSummary(
                model_id="demucs-other",
                kind="local",
                category="separator",
                backend="demucs",
                display_name="other",
                capability_models=["other"],
            ),
            ModelSummary(
                model_id="demucs-htdemucs",
                kind="local",
                category="separator",
                backend="demucs",
                display_name="HTDemucs",
                capability_models=["htdemucs"],
            ),
        ]
        models.get_model_status.return_value = ModelStatusView(
            model_id="demucs-htdemucs",
            status="installed",
            detail="ready",
            executable=True,
        )
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=descriptors,
            model_service=models,
        )
        service.ensure_workspace()

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={
                "stages": {
                    "separate": {
                        "enabled": True,
                        "provider": "demucs",
                        "model": "htdemucs",
                    }
                }
            },
        )

        assert result["ready"] is True
        models.get_model_status.assert_called_once_with("demucs-htdemucs")

    def test_pipeline_readiness_ignores_disabled_stage(self, tmp_path):
        from src.app.services.resource_service import ResourceService

        descriptors = MagicMock()
        models = MagicMock()
        models.list_models.return_value = []
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=descriptors,
            model_service=models,
        )

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={
                "stages": {
                    "translate": {
                        "enabled": False,
                        "provider": "missing-provider",
                        "model": None,
                    }
                }
            },
        )

        assert result["ready"] is True
        descriptors.get_descriptor.assert_not_called()

    def test_pipeline_readiness_checks_provider_runtime_dependency(self, tmp_path):
        from src.app.services.resource_service import ResourceService

        descriptors = MagicMock()
        descriptors.get_descriptor.return_value = {
            "supported_models": ["default"],
            "default_model": "default",
            "runtime_requirements": {
                "python_modules": ["edge_tts"],
                "system_tools": [],
            },
        }
        models = MagicMock()
        models.list_models.return_value = []
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=descriptors,
            model_service=models,
            module_checker=lambda module: module != "edge_tts",
        )

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={
                "stages": {
                    "tts": {
                        "enabled": True,
                        "provider": "edge",
                        "model": None,
                    }
                }
            },
        )

        assert result["ready"] is False
        assert result["issues"][0]["code"] == "PYTHON_DEPENDENCY_MISSING"
        assert result["issues"][0]["requirement"] == "edge_tts"

    def test_pipeline_readiness_checks_ffmpeg_for_mix(self, tmp_path):
        from src.app.services.resource_service import ResourceService

        models = MagicMock()
        models.list_models.return_value = []
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=MagicMock(),
            model_service=models,
            ffmpeg_checker=lambda: (False, "Bundled FFmpeg could not be started"),
        )

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={
                "stages": {
                    "mix": {
                        "enabled": True,
                        "provider": "ffmpeg",
                        "model": None,
                    }
                }
            },
        )

        assert result["ready"] is False
        assert result["issues"][0]["code"] == "SYSTEM_TOOL_MISSING"
        assert result["issues"][0]["stage"] == "mix"

    def test_pipeline_readiness_rejects_undecodable_input(self, tmp_path):
        from src.app.services.resource_service import ResourceService

        input_file = tmp_path / "broken.wav"
        input_file.write_bytes(b"not audio")
        models = MagicMock()
        models.list_models.return_value = []
        service = ResourceService(
            project_root=tmp_path,
            descriptor_service=MagicMock(),
            model_service=models,
            media_probe=lambda path: (False, f"Cannot decode {path}"),
        )

        result = service.check_task_readiness(
            task_type="pipeline",
            execution_profile={"stages": {}},
            input_path=str(input_file),
        )

        assert result["ready"] is False
        assert result["issues"][0]["code"] == "INPUT_MEDIA_INVALID"
        assert result["issues"][0]["action"] == "workbench"


class TestSubtitleService:
    """Test SubtitleService document operations."""

    def test_from_timestamp_entries_round_trip(self):
        from src.app.services.subtitle_service import SubtitleService

        entries = [
            {"start": 0.0, "end": 1.25, "text": "hello"},
            {"start": 1.25, "end": 2.5, "text": "world"},
        ]
        service = SubtitleService()
        document = service.from_timestamp_entries(entries)
        restored = service.to_timestamp_entries(document)
        assert restored == entries

    def test_parse_srt_text(self):
        from src.app.services.subtitle_service import SubtitleService

        content = "1\n00:00:00,000 --> 00:00:01,250\nhello\n\n2\n00:00:01,250 --> 00:00:03,500\nworld\n"
        service = SubtitleService()
        document = service.parse_text(content, fmt="srt")

        assert len(document.segments) == 2
        assert document.segments[0].text == "hello"
        assert document.segments[1].end == 3.5

    def test_export_srt_text(self):
        from src.app.dto import SubtitleDocument, SubtitleSegment
        from src.app.services.subtitle_service import SubtitleService

        document = SubtitleDocument(
            segments=[
                SubtitleSegment(start=0.0, end=1.25, text="hello"),
                SubtitleSegment(start=1.25, end=3.5, text="world"),
            ]
        )
        service = SubtitleService()
        exported = service.export_srt_text(document)

        assert "hello" in exported
        assert "-->" in exported

    def test_translate_subtitle_executes_real_path_branch(self, tmp_path, monkeypatch):
        from src.app.services.subtitle_service import SubtitleService

        subtitle_file = tmp_path / "source.srt"
        subtitle_file.write_text(
            "1\n00:00:00,000 --> 00:00:01,250\nhello\n",
            encoding="utf-8",
        )

        class FakeLlmRuntime:
            def translate_texts(self, **kwargs):
                assert kwargs["texts"] == ["hello"]
                return ["你好"]

        monkeypatch.setattr(
            "src.core.engines.llm.LlmOperationRuntime",
            FakeLlmRuntime,
        )

        result = SubtitleService().translate_subtitle(
            input_path=str(subtitle_file),
            provider="deepseek",
            source_lang="en",
            target_lang="zh",
        )

        output = Path(result.output_path)
        assert output.name == "source_zh.srt"
        assert output.exists()
        assert "你好" in output.read_text(encoding="utf-8")
        assert result.total_segments == 1


class TestPipelineServiceImport:
    """Test PipelineService can be imported and constructed."""

    def test_import_and_construct(self):
        from src.app.services.pipeline_service import PipelineService
        # Should not raise
        service = PipelineService()
        assert service._executor is not None


class TestAudioToolTaskSpec:
    def test_custom_output_dir_selects_custom_session_policy(self, tmp_path):
        from src.app.services.audio_tool_service import AudioToolService

        task_service = MagicMock()
        task_service.create_task_spec.return_value = (MagicMock(task_id="tool.convert-1"), False)
        workspace_service = MagicMock()
        workspace_service.resolve.return_value = MagicMock(workspace_id="workspace-1")
        input_catalog_service = MagicMock()
        input_catalog_service.inspect_paths.return_value = [
            MagicMock(asset_id="asset-1", kind="audio")
        ]
        session_service = MagicMock()
        output_dir = tmp_path / "custom-output"
        service = AudioToolService(
            task_service=task_service,
            workspace_service=workspace_service,
            input_catalog_service=input_catalog_service,
            session_service=session_service,
            artifact_service=MagicMock(),
            subtitle_service=MagicMock(),
            separator_runtime=MagicMock(),
        )

        service.create_tool_task_spec(
            task_type="tool.convert",
            input_path="input.wav",
            execution_profile={"output_dir": str(output_dir)},
        )

        assert session_service.create_session.call_args.kwargs["output_policy"] == {
            "mode": "custom-dir",
            "custom_output_dir": str(output_dir),
        }


class TestPipelineServiceCallbacks:
    """Test PipelineService progress/cancel passthrough semantics."""

    def _make_service(self):
        from src.app.dto import PipelineRequest
        from src.app.services.pipeline_service import PipelineService

        task_service = MagicMock()
        task_service.complete_task.return_value = MagicMock(task_id="pipeline-1", state="completed")
        resource_service = MagicMock()
        resource_service.ensure_workspace.return_value = {"output_dir": Path("/tmp/output")}
        input_catalog_service = MagicMock()
        input_catalog_service.get_asset.return_value = MagicMock(absolute_path="/tmp/input.wav")
        session_service = MagicMock()
        session_service.get_session.return_value = MagicMock(
            resolved_output_dir="/tmp/output",
            companion_asset_ids=[],
        )
        artifact_service = MagicMock()
        executor = MagicMock()

        service = PipelineService(
            task_service=task_service,
            resource_service=resource_service,
            input_catalog_service=input_catalog_service,
            session_service=session_service,
            artifact_service=artifact_service,
            executor=executor,
        )
        task_spec = MagicMock(
            task_id="pipeline-1",
            session_id="session-1",
            input_asset_id="asset-1",
            execution_profile=PipelineService._resolve_execution_profile(
                PipelineRequest(input_path="/tmp/input.wav")
            ),
        )
        return service, executor, task_service, task_spec

    def test_progress_callback_and_cancel_event_are_forwarded(self):
        service, executor, task_service, task_spec = self._make_service()
        cancel_event = threading.Event()
        messages: list[str] = []

        def run(plan, *, progress_callback=None, stage_callback=None, cancel_event=None):
            assert cancel_event is not None
            progress_callback("[1/5] 人声分离...")
            stage_callback("separate", 0.2, "[1/5] 人声分离...")
            return {
                "input": "/tmp/input.wav",
                "mix_path": "/tmp/output/input_mix.wav",
                "exported_subtitle": None,
                "primary_output": "/tmp/output/input_mix.wav",
                "steps": {},
                "step_errors": {},
                "total_duration": 1.23,
                "error": None,
            }

        executor.execute.side_effect = run

        result = service.run_pipeline_task_spec(
            task_spec,
            progress_callback=messages.append,
            cancel_event=cancel_event,
        )

        assert messages == ["[1/5] 人声分离..."]
        task_service.update_progress.assert_any_call(
            "pipeline-1",
            progress=0.1,
            message="[1/5] 人声分离...",
        )
        task_service.update_progress.assert_any_call(
            "pipeline-1",
            progress=0.2,
            message="[1/5] 人声分离...",
            stage="separate",
        )
        assert result.mix_path == "/tmp/output/input_mix.wav"

    def test_prepare_rechecks_v1_readiness_and_fails_task(self):
        from src.app.errors import ResourceValidationError

        service, executor, task_service, task_spec = self._make_service()
        task_spec.execution_profile = {
            "version": 1,
            "stages": {
                "asr": {
                    "enabled": True,
                    "provider": "faster_whisper",
                    "model": "faster-whisper-base",
                }
            },
        }
        service._resource_service.check_task_readiness.return_value = {
            "ready": False,
            "missing_requirements": ["faster_whisper"],
            "issues": [
                {
                    "stage": "asr",
                    "message": "Python dependency is unavailable: faster_whisper",
                }
            ],
        }

        with pytest.raises(ResourceValidationError, match="pipeline readiness check failed"):
            service.run_pipeline_task_spec(task_spec)

        executor.execute.assert_not_called()
        failure = task_service.fail_task.call_args.kwargs
        assert failure["stage"] == "prepare"
        assert "faster_whisper" in failure["detail"]

    def test_create_pipeline_task_rejects_unready_v1_profile(self):
        from src.app.dto import PipelineRequest
        from src.app.errors import ResourceValidationError
        from src.app.services.pipeline_service import PipelineService

        resource_service = MagicMock()
        resource_service.check_task_readiness.return_value = {
            "ready": False,
            "missing_requirements": ["api.deepseek_api_key"],
            "issues": [
                {
                    "stage": "translate",
                    "message": "Required provider credential is not configured",
                }
            ],
        }
        input_catalog_service = MagicMock()
        service = PipelineService(
            resource_service=resource_service,
            task_service=MagicMock(),
            workspace_service=MagicMock(),
            input_catalog_service=input_catalog_service,
            session_service=MagicMock(),
            artifact_service=MagicMock(),
            executor=MagicMock(),
        )
        request = PipelineRequest(
            input_path="input.wav",
            execution_profile={"version": 1, "stages": {}},
        )

        with pytest.raises(ResourceValidationError, match="translate"):
            service.create_pipeline_task(request)

        input_catalog_service.inspect_paths.assert_not_called()

    def test_flat_pipeline_request_is_normalized_before_readiness(self):
        from src.app.dto import PipelineRequest
        from src.app.errors import ResourceValidationError
        from src.app.services.pipeline_service import PipelineService

        resource_service = MagicMock()
        resource_service.check_task_readiness.return_value = {
            "ready": False,
            "missing_requirements": ["api.deepseek_api_key"],
            "issues": [
                {
                    "stage": "translate",
                    "message": "Required provider credential is not configured",
                }
            ],
        }
        input_catalog_service = MagicMock()
        service = PipelineService(
            resource_service=resource_service,
            task_service=MagicMock(),
            workspace_service=MagicMock(),
            input_catalog_service=input_catalog_service,
            session_service=MagicMock(),
            artifact_service=MagicMock(),
            executor=MagicMock(),
        )

        with pytest.raises(ResourceValidationError, match="translate"):
            service.create_pipeline_task(PipelineRequest(input_path="input.wav"))

        readiness_profile = resource_service.check_task_readiness.call_args.kwargs[
            "execution_profile"
        ]
        assert readiness_profile["version"] == 1
        assert readiness_profile["stages"]["separate"]["provider"] == "demucs"
        assert "profile_version" not in readiness_profile
        input_catalog_service.inspect_paths.assert_not_called()

    def test_cancellation_marks_task_cancelled(self):
        from src.app.errors import AppExecutionError

        service, executor, task_service, task_spec = self._make_service()
        cancel_event = threading.Event()
        cancel_event.set()
        executor.execute.side_effect = RuntimeError("用户取消操作")

        with pytest.raises(AppExecutionError, match="用户取消操作"):
            service.run_pipeline_task_spec(task_spec, cancel_event=cancel_event)

        task_service.cancel_task.assert_called_once_with(
            "pipeline-1",
            message="cancelled by user",
        )
        task_service.fail_task.assert_not_called()

    @pytest.mark.parametrize(
        ("step_errors", "expected_stage", "expected_code", "expected_detail"),
        [
            (
                {
                    "vocal_separator": "No module named 'torch'",
                    "asr": "No module named 'faster_whisper'",
                },
                "separate",
                "PROVIDER_DEPENDENCY_MISSING",
                "No module named 'torch'",
            ),
            (
                {"tts": "No audio was received. Please verify the parameters."},
                "tts",
                "PROVIDER_RESPONSE_INVALID",
                "No audio was received. Please verify the parameters.",
            ),
        ],
    )
    def test_first_stage_error_is_reported_with_stable_contract(
        self,
        step_errors,
        expected_stage,
        expected_code,
        expected_detail,
    ):
        from src.app.errors import AppExecutionError

        service, executor, task_service, task_spec = self._make_service()
        executor.execute.return_value = {"step_errors": step_errors}

        with pytest.raises(AppExecutionError, match=expected_stage):
            service.run_pipeline_task_spec(task_spec)

        failure = task_service.fail_task.call_args.kwargs
        assert failure["stage"] == expected_stage
        assert failure["detail"] == expected_detail
        assert failure["error"]["code"] == expected_code
        assert failure["error"]["stage"] == expected_stage
        assert failure["error"]["retryable"] is True


class TestBatchPipelineServiceCompanions:
    """Test companion subtitle discovery in batch task creation."""

    def test_create_batch_task_specs_passes_auto_discovered_subtitle(self, tmp_path):
        from src.app.dto.batch_pipeline import BatchPipelineRequest
        from src.app.services.batch_pipeline_service import BatchPipelineService

        audio_file = tmp_path / "sample.wav"
        audio_file.write_bytes(b"audio")

        pipeline_service = MagicMock()
        pipeline_service.create_pipeline_task.return_value = (
            MagicMock(task_id="pipeline-1"),
            MagicMock(task_id="pipeline-1"),
        )
        input_catalog_service = MagicMock()
        input_catalog_service.inspect_paths.return_value = [
            MagicMock(asset_id="asset-1", absolute_path=str(audio_file))
        ]
        input_catalog_service.discover_companions.return_value = [
            MagicMock(kind="subtitle", absolute_path=str(tmp_path / "sample.vtt"))
        ]

        service = BatchPipelineService(
            pipeline_service=pipeline_service,
            input_catalog_service=input_catalog_service,
        )
        request = BatchPipelineRequest(input_files=[str(audio_file)])

        service.create_batch_task_specs(request)

        request_arg = pipeline_service.create_pipeline_task.call_args.args[0]
        assert request_arg.vtt_path == str(tmp_path / "sample.vtt")
        assert request_arg.asr_model == "faster-whisper-base"
