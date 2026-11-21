"""Current application-layer service contracts."""

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

    def validate(self, candidate, *, require_api_key=True):
        return True, []

    def persist_updates(self, updates):
        self.persisted = deepcopy(updates)
        self._merge(self.data, updates)


class TestSettingsService:
    def test_custom_llm_model_roundtrip_and_execution(self):
        from src.app.services.settings_service import SettingsService
        from src.app.services.execution_profile_builder import ExecutionProfileBuilder
        from src.core.engines.llm.service import LlmOperationRuntime

        config = _FakeConfig()
        settings = SettingsService(config_manager=config)
        result = settings.update_settings({"providers": {
            "default_llm": "openai",
            "openai": {"model": " vendor/custom-model ", "base_url": "https://gateway.invalid/v1"},
        }})
        assert result["providers"]["openai"]["model"] == "vendor/custom-model"
        assert config.data["api"]["deepseek_api_key"] == "secret-deepseek"
        builder = ExecutionProfileBuilder(settings_service=settings)
        for model in (None, "default", " "):
            profile = builder.build(category="llm", model=model)
            assert profile["provider"] == "openai"
            assert profile["model"] == "vendor/custom-model"
        profile = builder.build(category="llm", provider="openai", model=" another/model ")
        registry = MagicMock()
        LlmOperationRuntime(registry=registry)._get_translator(profile)
        registry.get.assert_called_once_with("openai", model="another/model", base_url=None)

    @pytest.mark.parametrize("model", ["", "  ", None, 42])
    def test_invalid_model_setting_does_not_persist(self, model):
        from src.app.services.settings_service import SettingsService
        from src.app.errors import AppValidationError

        config = _FakeConfig()
        with pytest.raises(AppValidationError, match="模型 ID"):
            SettingsService(config_manager=config).update_settings({
                "providers": {"openai": {"model": model}},
            })
        assert config.persisted is None

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
            service.update_settings({"paths": {"output_dir": "test-output"}})


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

    def test_llm_capability_models_come_from_runtime_registry(self, monkeypatch):
        from src.app.services.capability_descriptor_service import (
            CapabilityDescriptorService,
        )
        from src.core.engines.llm import get_llm_registry
        from src.core.engines.llm.registry import LLM_SUPPORTED_MODELS
        from src.core.engines.llm.translator import Translator
        from src.config import config

        # Exercise the registry fallback independently of the user's saved model.
        monkeypatch.setattr(config, "get", lambda *_args, **_kwargs: None)

        registry = get_llm_registry()
        descriptor = CapabilityDescriptorService().get_descriptor("llm", "deepseek")

        assert descriptor["default_model"] == registry.default_model("deepseek")
        assert descriptor["default_model"] == "deepseek-chat"
        assert descriptor["supported_models"] == registry.list_models("deepseek")
        assert Translator.MODELS is LLM_SUPPORTED_MODELS

    @pytest.mark.parametrize("provider", ["deepseek", "openai"])
    def test_llm_capability_exposes_duration_controls_and_rejects_ignored_options(
        self,
        provider: str,
    ):
        from src.app.errors import AppValidationError
        from src.app.services.capability_descriptor_service import (
            CapabilityDescriptorService,
        )

        service = CapabilityDescriptorService()
        descriptor = service.get_descriptor("llm", provider)

        assert {option["name"] for option in descriptor["common_option_schema"]} == {
            "duration_aware", "chars_per_second",
        }
        service.validate_options(
            category="llm", provider=provider,
            common_options={"duration_aware": True, "chars_per_second": 4.5},
        )
        with pytest.raises(
            AppValidationError,
            match="unsupported options: max_tokens, temperature",
        ):
            service.validate_options(
                category="llm",
                provider=provider,
                common_options={"temperature": 0.2, "max_tokens": 1024},
            )


class TestModelService:
    def test_list_models_normalizes_missing_install_strategy(self):
        from src.app.services.model_service import ModelService

        from src.core.resources.model_catalog import ModelEntry

        core_service = MagicMock()
        core_service.list_models.return_value = [
            ModelEntry(
                id="deepseek",
                kind="cloud",
                category="llm",
                provider="deepseek",
                display_name="DeepSeek API",
                description="Remote translation",
                install_strategy=None,
            )
        ]

        models = ModelService(core_service=core_service).list_models()

        assert models[0].install_strategy == ""
        assert models[0].description == "Remote translation"

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

    def test_local_model_verification_requires_executable_runtime(self):
        from src.app.services.model_service import ModelService
        from src.core.resources.model_status import (
            ModelState,
            ModelStatus,
            ModelStatusIssue,
        )

        core_service = MagicMock()
        core_service.get_model.return_value = SimpleNamespace(kind="local")
        core_service.verify.return_value = {"fun-asr-nano-2512": True}
        core_service.get_status.return_value = ModelStatus(
            model_id="fun-asr-nano-2512",
            status=ModelState.INSTALLED,
            detail="Model is installed but runtime requirements are unavailable",
            executable=False,
            issues=(
                ModelStatusIssue(
                    code="PYTHON_DEPENDENCY_MISSING",
                    requirement="torchaudio",
                    message="Python dependency is unavailable: torchaudio",
                ),
            ),
        )

        result = ModelService(core_service=core_service).verify_models(
            "fun-asr-nano-2512"
        )[0]

        assert result.success is False
        assert result.status == ModelState.INSTALLED
        assert [(issue.code, issue.requirement) for issue in result.issues] == [
            ("PYTHON_DEPENDENCY_MISSING", "torchaudio")
        ]


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
                task_type="tool.convert",
                task_source="test",
                session_id="session-1",
            )

        assert service.list_tasks() == []

    def test_state_persistence_failure_quarantines_task_as_failed(self):
        from src.app.errors import AppExecutionError
        from src.app.services.task_service import TaskService

        service = TaskService(state_store=self._FailingStateStore(fail_state="running"))
        spec, _ = service.create_task_spec(
            task_type="tool.convert",
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

    def test_create_task_spec_and_lifecycle(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, status = service.create_task_spec(
            task_type="tool.convert",
            task_source="test",
            session_id="session-1",
            input_asset_id="asset-1",
        )

        assert spec.task_id
        assert spec.task_type == "tool.convert"
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
            task_type="tool.convert",
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

    def test_get_unknown_task_raises(self):
        from src.app.errors import AppValidationError
        from src.app.services.task_service import TaskService

        service = TaskService()
        with pytest.raises(AppValidationError):
            service.get_task("nonexistent-id")

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
        assert statuses["output_dir"].available is False

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

    def test_parse_and_export_srt_round_trip(self):
        from src.app.services.subtitle_service import SubtitleService

        content = "1\n00:00:00,000 --> 00:00:01,250\nhello\n\n2\n00:00:01,250 --> 00:00:03,500\nworld\n"
        service = SubtitleService()
        document = service.parse_text(content, fmt="srt")

        assert len(document.segments) == 2
        assert document.segments[0].text == "hello"
        assert document.segments[1].end == 3.5
        exported = service.export_srt_text(document)
        assert "00:00:01,250 --> 00:00:03,500" in exported
        assert service.to_timestamp_entries(service.parse_text(exported, fmt="srt")) == (
            service.to_timestamp_entries(document)
        )

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
