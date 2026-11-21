"""Current application-layer service contracts."""

from __future__ import annotations

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


class TestCapabilityOptionContract:
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


class TestSubtitleService:
    """Test SubtitleService document operations."""


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
