"""Integration tests for slices 02-04: session/task chain, artifacts, engine registry."""

from __future__ import annotations

import threading

import pytest

from src.app.dto import (
    ArtifactRecord,
    ArtifactSet,
    InputAsset,
    ProcessingSession,
    SubtitleAsset,
    SubtitleDocument,
    SubtitleSegment,
    TaskSpec,
    TaskStatus,
    WorkspaceContext,
)
from src.app.errors import AppValidationError
from src.app.services.artifact_service import ArtifactService
from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.app.services.execution_profile_builder import ExecutionProfileBuilder
from src.app.services.input_catalog_service import InputCatalogService
from src.app.services.settings_service import SettingsService
from src.app.services.task_service import TaskService
from src.app.services.workspace_service import WorkspaceService


# ---------------------------------------------------------------------------
# Slice 02: TaskService state machine
# ---------------------------------------------------------------------------


class TestTaskServiceStateMachine:
    def setup_method(self):
        self.svc = TaskService(max_concurrent=2)

    def test_create_task_spec(self):
        spec, task = self.svc.create_task_spec(
            task_type="pipeline",
            task_source="manual",
            session_id="sess-1",
        )
        assert spec.task_id == task.task_id
        assert task.state == "pending"
        assert spec.task_type == "pipeline"
        assert spec.session_id == "sess-1"

    def test_lifecycle_pending_running_completed(self):
        _, task = self.svc.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        tid = task.task_id

        task = self.svc.start_task(tid)
        assert task.state == "running"

        task = self.svc.update_progress(tid, 0.5, "halfway")
        assert task.progress == 0.5
        assert task.message == "halfway"

        task = self.svc.complete_task(tid, "done")
        assert task.state == "completed"
        assert task.progress == 1.0

    def test_lifecycle_pending_running_failed(self):
        _, task = self.svc.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        tid = task.task_id
        self.svc.start_task(tid)
        task = self.svc.fail_task(tid, "error occurred")
        assert task.state == "failed"
        assert task.message == "error occurred"

    def test_cancel_pending_task(self):
        _, task = self.svc.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        task = self.svc.cancel_task(task.task_id)
        assert task.state == "cancelled"

    def test_cancel_running_task(self):
        _, task = self.svc.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        self.svc.start_task(task.task_id)
        task = self.svc.cancel_task(task.task_id)
        assert task.state == "cancelled"

    def test_cancel_terminal_task_raises(self):
        _, task = self.svc.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1"
        )
        self.svc.complete_task(task.task_id)
        with pytest.raises(AppValidationError, match="cannot cancel"):
            self.svc.cancel_task(task.task_id)

    def test_cancel_unknown_task_raises(self):
        with pytest.raises(AppValidationError, match="unknown"):
            self.svc.cancel_task("nonexistent")

    def test_concurrency_control(self):
        assert self.svc.can_start() is True
        assert self.svc.running_count() == 0

        specs = []
        for i in range(2):
            _, task = self.svc.create_task_spec(
                task_type="pipeline", task_source="test", session_id=f"s{i}"
            )
            self.svc.start_task(task.task_id)
            specs.append(task)

        assert self.svc.running_count() == 2
        assert self.svc.can_start() is False

        self.svc.complete_task(specs[0].task_id)
        assert self.svc.running_count() == 1
        assert self.svc.can_start() is True

    def test_skip_task(self):
        _, task = self.svc.create_task_spec(
            task_type="tool", task_source="test", session_id="s1"
        )
        task = self.svc.skip_task(task.task_id, "already done")
        assert task.state == "skipped"

    def test_list_tasks(self):
        for i in range(3):
            self.svc.create_task_spec(
                task_type="pipeline", task_source="test", session_id=f"s{i}"
            )
        tasks = self.svc.list_tasks()
        assert len(tasks) == 3

    def test_get_task_spec(self):
        spec, _ = self.svc.create_task_spec(
            task_type="pipeline",
            task_source="test",
            session_id="s1",
            execution_profile={"tts": {"engine": "edge"}},
        )
        retrieved = self.svc.get_task_spec(spec.task_id)
        assert retrieved.execution_profile == {"tts": {"engine": "edge"}}


# ---------------------------------------------------------------------------
# Slice 02: Workspace → Input → Session chain
# ---------------------------------------------------------------------------


class TestWorkspaceInputSessionChain:
    def test_workspace_resolve(self):
        svc = WorkspaceService()
        ctx = svc.resolve()
        assert isinstance(ctx, WorkspaceContext)
        assert ctx.workspace_id
        assert ctx.workspace_root
        assert ctx.default_output_root
        assert ctx.default_temp_root
        assert ctx.default_models_root

    def test_input_inspect_nonexistent(self):
        svc = InputCatalogService()
        assets = svc.inspect_paths(["/nonexistent/file.mp3"])
        assert len(assets) == 1
        assert assets[0].exists is False

    def test_input_asset_fields(self):
        asset = InputAsset(
            asset_id="a1",
            absolute_path="/tmp/test.mp3",
            kind="audio",
            display_name="test.mp3",
            extension=".mp3",
        )
        assert asset.kind == "audio"
        assert asset.extension == ".mp3"


# ---------------------------------------------------------------------------
# Slice 03: SubtitleDocument / SubtitleAsset
# ---------------------------------------------------------------------------


class TestSubtitleDTO:
    def test_subtitle_segment_with_language(self):
        seg = SubtitleSegment(start=0.0, end=1000.0, text="hello", language="en", confidence=0.95)
        assert seg.language == "en"
        assert seg.confidence == 0.95

    def test_subtitle_document_properties(self):
        doc = SubtitleDocument(
            segments=[
                SubtitleSegment(start=0, end=1000, text="a"),
                SubtitleSegment(start=1000, end=2000, text="b"),
            ],
            language="ja",
            format="srt",
        )
        assert doc.line_count == 2
        assert doc.duration_ms == 2000.0
        assert doc.language == "ja"

    def test_subtitle_asset_with_companion(self):
        asset = SubtitleAsset(
            asset_id="sa1",
            format="srt",
            language="ja",
            companion_of="audio-1",
        )
        assert asset.companion_of == "audio-1"
        assert asset.language == "ja"


# ---------------------------------------------------------------------------
# Slice 03: ArtifactService
# ---------------------------------------------------------------------------


class TestArtifactService:
    def setup_method(self):
        self.svc = ArtifactService()

    def test_register_and_retrieve(self):
        record = self.svc.register_artifact(
            task_id="t1",
            artifact_type="audio.mix",
            path="/output/mix.wav",
            is_primary=True,
        )
        assert record.artifact_id
        assert record.is_primary is True

        retrieved = self.svc.get_artifact(record.artifact_id)
        assert retrieved.path == "/output/mix.wav"

    def test_task_artifacts(self):
        self.svc.register_artifact(task_id="t1", artifact_type="audio.mix", path="/mix.wav", is_primary=True)
        self.svc.register_artifact(task_id="t1", artifact_type="subtitle.srt", path="/sub.srt")

        artifact_set = self.svc.get_task_artifacts("t1")
        assert len(artifact_set.entries) == 2
        assert artifact_set.primary_output == "/mix.wav"
        assert "mix" in artifact_set.files

    def test_result_view_primary_detection(self):
        self.svc.register_artifact(task_id="t1", artifact_type="audio.vocals", path="/vocals.wav")
        self.svc.register_artifact(task_id="t1", artifact_type="audio.mix", path="/mix.wav", is_primary=True)

        view = self.svc.get_task_result_view("t1")
        assert view["primary_output"].path == "/mix.wav"
        assert len(view["secondary_outputs"]) == 1

    def test_empty_task_returns_empty(self):
        artifact_set = self.svc.get_task_artifacts("nonexistent")
        assert len(artifact_set.entries) == 0

    def test_result_view_empty_task(self):
        view = self.svc.get_task_result_view("nonexistent")
        assert view["primary_output"] is None
        assert view["secondary_outputs"] == []


# ---------------------------------------------------------------------------
# Slice 03: CapabilityDescriptorService
# ---------------------------------------------------------------------------


class TestCapabilityDescriptorService:
    def setup_method(self):
        self.svc = CapabilityDescriptorService()

    def test_list_categories(self):
        categories = self.svc.list_categories()
        assert "tts" in categories
        assert "llm" in categories
        assert "asr" in categories
        assert "separator" in categories

    def test_list_tts_descriptors(self):
        descriptors = self.svc.list_descriptors(category="tts")
        providers = {d["provider"] for d in descriptors}
        assert "edge" in providers
        assert "qwen3" in providers

    def test_get_descriptor(self):
        desc = self.svc.get_descriptor("tts", "edge")
        assert desc["display_name"] == "Edge TTS"
        assert desc["kind"] == "cloud"

    def test_get_descriptor_not_found(self):
        with pytest.raises(AppValidationError, match="not found"):
            self.svc.get_descriptor("tts", "nonexistent")

    def test_filter_by_provider(self):
        descriptors = self.svc.list_descriptors(provider="deepseek")
        assert len(descriptors) == 1
        assert descriptors[0]["category"] == "llm"


# ---------------------------------------------------------------------------
# Slice 04: ExecutionProfileBuilder
# ---------------------------------------------------------------------------


class TestExecutionProfileBuilder:
    def setup_method(self):
        self.builder = ExecutionProfileBuilder()

    def test_build_tts_profile(self):
        profile = self.builder.build(category="tts", provider="edge")
        assert profile["category"] == "tts"
        assert profile["provider"] == "edge"
        assert "voice" in profile["common_options"]

    def test_build_asr_profile(self):
        profile = self.builder.build(category="asr", provider="faster_whisper")
        assert profile["category"] == "asr"
        assert profile["provider"] == "faster_whisper"
        assert profile["model"] in ("tiny", "base", "small", "medium", "large-v3")

    def test_build_llm_profile(self):
        profile = self.builder.build(category="llm", provider="deepseek")
        assert profile["category"] == "llm"
        assert profile["provider"] == "deepseek"

    def test_build_with_overrides(self):
        profile = self.builder.build(
            category="tts",
            provider="edge",
            common_options={"speed": 1.5},
        )
        assert profile["common_options"]["speed"] == 1.5


# ---------------------------------------------------------------------------
# Slice 04: Engine service utility methods
# ---------------------------------------------------------------------------


class TestEngineServiceUtilities:
    def test_tts_list_supported_models(self):
        from src.app.services.tts_engine_service import TtsEngineService

        svc = TtsEngineService()
        models = svc.list_supported_models("edge")
        assert "default" in models

    def test_tts_get_default_voice(self):
        from src.app.services.tts_engine_service import TtsEngineService

        svc = TtsEngineService()
        voice = svc.get_default_voice("edge")
        assert voice == "zh-CN-XiaoxiaoNeural"

    def test_tts_engine_supports(self):
        from src.app.services.tts_engine_service import TtsEngineService

        svc = TtsEngineService()
        assert svc.engine_supports("qwen3", "voice_clone") is True
        assert svc.engine_supports("edge", "voice_clone") is False

    def test_asr_list_supported_models(self):
        from src.app.services.asr_engine_service import AsrEngineService

        svc = AsrEngineService()
        models = svc.list_supported_models("faster_whisper")
        assert "base" in models
        assert "large-v3" in models

    def test_asr_engine_supports(self):
        from src.app.services.asr_engine_service import AsrEngineService

        svc = AsrEngineService()
        assert svc.engine_supports("faster_whisper", "vad") is True

    def test_llm_list_providers(self):
        from src.app.services.llm_capability_service import LlmCapabilityService

        svc = LlmCapabilityService()
        providers = svc.list_providers()
        provider_ids = {p["provider"] for p in providers}
        assert "deepseek" in provider_ids
        assert "openai" in provider_ids

    def test_llm_provider_supports(self):
        from src.app.services.llm_capability_service import LlmCapabilityService

        svc = LlmCapabilityService()
        assert svc.provider_supports("openai", "json_mode") is True
        assert svc.provider_supports("deepseek", "json_mode") is False


# ---------------------------------------------------------------------------
# SettingsService
# ---------------------------------------------------------------------------


class TestSettingsService:
    def test_get_settings_masked(self):
        svc = SettingsService()
        settings = svc.get_settings(masked=True)
        assert isinstance(settings, dict)
        assert "api" in settings or "tts" in settings or "paths" in settings

    def test_get_settings_unmasked(self):
        svc = SettingsService()
        settings = svc.get_settings(masked=False)
        assert isinstance(settings, dict)
