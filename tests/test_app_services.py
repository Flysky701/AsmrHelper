"""Tests for application-layer services — current API contracts.

Covers TaskService, ResourceService, SubtitleService, and PipelineService
with their current interfaces.
"""

from __future__ import annotations

import threading

import pytest


class TestTaskService:
    """Test TaskService lifecycle and concurrency."""

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

        started = service.start_task(spec.task_id, message="running")
        assert started.state == "running"

        updated = service.update_progress(spec.task_id, progress=0.5, message="halfway")
        assert updated.progress == 0.5

        completed = service.complete_task(spec.task_id, message="done", detail="output.wav")
        assert completed.state == "completed"
        assert completed.progress == 1.0

    def test_fail_task(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="tool", task_source="test", session_id="s1",
        )
        service.start_task(spec.task_id)
        failed = service.fail_task(spec.task_id, message="error", detail="OOM")
        assert failed.state == "failed"

    def test_cancel_task(self):
        from src.app.services.task_service import TaskService

        service = TaskService()
        spec, _ = service.create_task_spec(
            task_type="pipeline", task_source="test", session_id="s1",
        )
        cancelled = service.cancel_task(spec.task_id)
        assert cancelled.state == "cancelled"

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


class TestPipelineServiceImport:
    """Test PipelineService can be imported and constructed."""

    def test_import_and_construct(self):
        from src.app.services.pipeline_service import PipelineService
        # Should not raise
        service = PipelineService()
        assert service._executor is not None
        assert service._use_legacy is False

    def test_use_legacy_flag(self):
        from src.app.services.pipeline_service import PipelineService
        service = PipelineService(use_legacy=True)
        assert service._use_legacy is True
