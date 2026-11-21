"""Tests for the FastAPI HTTP API layer."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.http.app import create_app
from src.api.http import dependencies
from src.app.dto import (
    ModelStatusView,
    TaskStatus,
    TranslationResult,
)


@pytest.fixture()
def client():
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_dep(mock_obj):
    """Return a lambda that returns the mock, suitable for dependency override."""
    return lambda: mock_obj


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCorsPolicy:
    def test_packaged_tauri_origin_is_allowed(self, client):
        response = client.options(
            "/api/v1/settings",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"

    def test_untrusted_web_origin_is_not_allowed(self, client):
        response = client.options(
            "/api/v1/settings",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


class TestPipelineRoutes:
    def test_list_presets_does_not_initialize_pipeline_runtime(self, client, monkeypatch, tmp_path):
        from src.app.services.preset_catalog_service import PresetCatalogService

        catalog = PresetCatalogService(user_presets_path=tmp_path / "presets.json")
        expected = catalog.list_presets()
        client.app.dependency_overrides[dependencies.preset_catalog_service] = lambda: catalog

        def fail_pipeline_initialization():
            raise AssertionError("preset catalog must not initialize pipeline runtime")

        monkeypatch.setattr(
            dependencies,
            "get_pipeline_service",
            fail_pipeline_initialization,
        )

        resp = client.get("/api/v1/pipeline/presets")

        assert resp.status_code == 200
        assert [preset["id"] for preset in resp.json()["presets"]] == [
            preset["id"] for preset in expected if preset.get("version") != 2
        ]
        graph_response = client.get("/api/v1/pipeline/presets?include_graph=true")
        assert graph_response.status_code == 200
        assert [preset["id"] for preset in graph_response.json()["presets"]] == [
            preset["id"] for preset in expected
        ]


class TestPipelineRunRoutes:
    def test_implicit_pipeline_is_rejected_before_submission(self, client):
        service = MagicMock()
        client.app.dependency_overrides[dependencies.pipeline_task_orchestrator] = _mock_dep(service)
        body = {"input": {"path": "/test/input.wav"}}
        assert client.post("/api/v1/pipeline-runs", json=body).status_code == 422
        service.submit_task.assert_not_called()


    def test_create_tool_task_uses_task_driven_contract(self, client):
        mock_svc = MagicMock()
        mock_svc.create_task.return_value = TaskStatus(
            task_id="tool.convert-1",
            task_type="tool.convert",
            state="pending",
            progress=0.0,
        )
        client.app.dependency_overrides[dependencies.tool_registry] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/tool-runs",
            json={
                "task_type": "tool.convert",
                "input_path": "/test/input.wav",
                "companion_paths": [],
                "execution_profile": {
                    "output_path": "/test/output.wav",
                    "target_format": "wav",
                },
            },
        )

        assert resp.status_code == 201
        assert resp.json()["task_id"] == "tool.convert-1"
        assert resp.json()["state"] == "pending"
        mock_svc.create_task.assert_called_once_with(
            task_type="tool.convert",
            input_path="/test/input.wav",
            companion_paths=[],
            execution_profile={
                "output_path": "/test/output.wav",
                "target_format": "wav",
            },
        )


class TestAsrRoutes:
    def test_transcribe_success(self, client):
        mock_svc = MagicMock()
        result_mock = MagicMock()
        result_mock.segments = [
            MagicMock(start=0.0, end=2.5, text="こんにちは"),
            MagicMock(start=2.5, end=5.0, text="世界"),
        ]
        result_mock.output_path = None
        result_mock.text = "こんにちは\n世界"
        mock_svc.transcribe_file.return_value = result_mock
        client.app.dependency_overrides[dependencies.asr_engine_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/asr/transcribe",
            json={"input_path": "/test/audio.wav"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["segments"]) == 2
        assert data["text"] == "こんにちは\n世界"


class TestTranslationRoutes:
    def test_translate_via_llm_success(self, client, tmp_path):
        mock_svc = MagicMock()
        mock_svc.translate_texts.return_value = TranslationResult(
            items=["你好", "世界"],
            provider="deepseek",
            source_lang="ja",
            target_lang="zh",
        )
        client.app.dependency_overrides[dependencies.llm_capability_service] = _mock_dep(mock_svc)

        # Create a real input file since the route checks existence
        input_file = tmp_path / "input.txt"
        input_file.write_text("こんにちは\n世界\n", encoding="utf-8")

        resp = client.post(
            "/api/v1/llm/translate",
            json={
                "input_path": str(input_file),
                "source_lang": "ja",
                "target_lang": "zh",
                "provider": "deepseek",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == ["你好", "世界"]
        assert data["provider"] == "deepseek"


class TestModelRoutes:
    def test_drama3_download_needs_consent_before_install_or_queue(self, client, monkeypatch):
        from src.app.services.model_service import ModelService

        service = ModelService(task_service=MagicMock(), dispatcher=MagicMock())
        installer = MagicMock()
        monkeypatch.setattr(service.core_service, "install", installer)
        client.app.dependency_overrides[dependencies.model_service] = lambda: service
        root = "/api/v1/models/fish_drama3/"
        for route in ("download", "install", "install?sync=true"):
            response = client.post(root + route, json={"force": True})
            assert response.status_code == 400
            assert "41.50 GB" in response.json()["error"]["message"]
        service._task_service.create_task_spec.assert_not_called()
        installer.assert_not_called()

        monkeypatch.setattr(service, "get_model_status", lambda _: ModelStatusView(
            model_id="fish_drama3", status="installed", detail="fixture",
        ))
        assert client.post(root + "install?sync=true", json={"confirm_large_download": True}).status_code == 200
        installer.assert_called_once()


class TestSubtitleRoutes:
    def test_create_script_to_subtitle_task_submits_background_work(self, client):
        mock_svc = MagicMock()
        mock_svc.create_task.return_value = TaskStatus(
            task_id="subtitle.script_to_vtt-1",
            task_type="subtitle.script_to_vtt",
            task_source="subtitle-workshop",
            state="running",
            stage="clean_script",
            progress=0.1,
            created_at="2026-08-07T00:00:00+00:00",
        )
        client.app.dependency_overrides[dependencies.script_subtitle_service] = _mock_dep(mock_svc)

        response = client.post(
            "/api/v1/subtitles/script-to-subtitle/tasks",
            json={"script_path": "script.txt", "fmt": "vtt"},
        )

        assert response.status_code == 201
        assert response.json()["task_id"] == "subtitle.script_to_vtt-1"
        assert response.json()["state"] == "running"
        request = mock_svc.create_task.call_args.args[0]
        assert request.script_path == "script.txt"
        assert request.fmt == "vtt"


    def test_export_subtitle_accepts_document_shape(self, client, tmp_path):
        mock_svc = MagicMock()
        mock_svc.export_document.return_value = str(tmp_path / "document-shape.srt")
        client.app.dependency_overrides[dependencies.subtitle_service] = _mock_dep(mock_svc)

        output_file = str(tmp_path / "document-shape.srt")
        resp = client.post(
            "/api/v1/subtitles/export",
            json={
                "document": {
                    "segments": [{"start": 0.0, "end": 2.5, "text": "Hello"}],
                },
                "output_path": output_file,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["segment_count"] == 1

    def test_translate_subtitle_registers_artifact(self, client, tmp_path):
        from src.app.dto import SubtitleTranslationResult

        output_path = str(tmp_path / "translated.vtt")
        mock_svc = MagicMock()
        mock_svc.translate_subtitle.return_value = SubtitleTranslationResult(
            input_path=str(tmp_path / "source.srt"),
            output_path=output_path,
            total_segments=2,
            provider="deepseek",
            source_lang="ja",
            target_lang="zh",
        )
        mock_artifacts = MagicMock()
        client.app.dependency_overrides[dependencies.subtitle_service] = _mock_dep(mock_svc)
        client.app.dependency_overrides[dependencies.artifact_service] = _mock_dep(mock_artifacts)

        resp = client.post(
            "/api/v1/subtitles/translate",
            json={
                "input_path": str(tmp_path / "source.srt"),
                "output_path": output_path,
                "task_id": "task-translate",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["total_segments"] == 2
        assert mock_artifacts.register_artifact.call_args.kwargs["artifact_type"] == "subtitle.vtt"


class TestResourceRoutes:
    def test_task_readiness_exposes_structured_issues(self, client):
        mock_svc = MagicMock()
        mock_svc.check_task_readiness.return_value = {
            "task_type": "pipeline",
            "ready": False,
            "missing_requirements": ["DEEPSEEK_API_KEY"],
            "issues": [
                {
                    "stage": "translate",
                    "category": "llm",
                    "provider": "deepseek",
                    "model": "deepseek",
                    "code": "CREDENTIAL_MISSING",
                    "requirement": "DEEPSEEK_API_KEY",
                    "message": "Required provider credential is not configured",
                    "action": "settings",
                }
            ],
            "execution_profile": {"stages": {}},
        }
        client.app.dependency_overrides[dependencies.resource_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/runtime/check-task-readiness",
            json={"task_type": "pipeline", "execution_profile": {"stages": {}}},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["issues"][0]["action"] == "settings"
        assert mock_svc.check_task_readiness.call_args.kwargs["input_path"] is None


class TestTaskRoutes:
    def test_create_task_submits_to_dispatcher(self, client):
        from src.api.http import dependencies
        from src.app.services.task_service import TaskService
        from src.core.tasks import ExecutorRegistry, TaskDispatcher

        registry = ExecutorRegistry()
        registry.register("contract.echo", lambda spec: {"detail": spec.task_id})
        task_svc = TaskService(executor_registry=registry)
        dispatcher = TaskDispatcher(task_svc.registry, task_service=task_svc)
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(task_svc)
        client.app.dependency_overrides[dependencies.task_dispatcher] = _mock_dep(dispatcher)

        resp = client.post(
            "/api/v1/tasks",
            json={
                "task_type": "contract.echo",
                "task_source": "http-test",
                "session_id": "session-1",
            },
        )

        assert resp.status_code == 200
        task_id = resp.json()["task"]["task_id"]
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if task_svc.get_task(task_id).state == "completed":
                break
            time.sleep(0.01)
        detail = client.get(f"/api/v1/tasks/{task_id}")
        assert detail.status_code == 200
        assert detail.json()["state"] == "completed"
        listing = client.get("/api/v1/tasks")
        assert task_id in {item["task_id"] for item in listing.json()["tasks"]}


    def test_batch_task_submission_validates_all_handlers_before_creation(self, client):
        from src.api.http import dependencies
        from src.app.services.task_service import TaskService
        from src.core.tasks import ExecutorRegistry, TaskDispatcher

        executed = []
        registry = ExecutorRegistry()
        registry.register("contract.echo", lambda spec: executed.append(spec.task_id) or {})
        registry.register("declared.only")
        task_svc = TaskService(executor_registry=registry)
        dispatcher = TaskDispatcher(task_svc.registry, task_service=task_svc)
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(task_svc)
        client.app.dependency_overrides[dependencies.task_dispatcher] = _mock_dep(dispatcher)

        resp = client.post(
            "/api/v1/tasks/batch",
            json={
                "items": [
                    {"task_type": "contract.echo", "session_id": "session-1"},
                    {"task_type": "declared.only", "session_id": "session-1"},
                ]
            },
        )

        assert resp.status_code == 400
        assert task_svc.list_tasks() == []
        assert executed == []


    def test_task_events_stream_runtime_event_contract(self, client):
        from src.core.tasks import RuntimeEvent

        mock_svc = MagicMock()
        mock_svc.list_events.return_value = [
            RuntimeEvent(
                sequence=3,
                time="2026-07-24T10:00:00+00:00",
                level="info",
                type="stage_progress",
                task_id="pipeline-1",
                stage="asr",
                message="decoded segment 24",
                data={"state": "completed", "progress": 1.0},
            )
        ]
        mock_svc.get_task.return_value = TaskStatus(
            task_id="pipeline-1",
            state="completed",
            progress=1.0,
        )
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tasks/pipeline-1/events?after_sequence=2")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "id: 3" in resp.text
        assert "event: runtime" in resp.text
        assert '"type":"stage_progress"' in resp.text
        assert "event: done" in resp.text
        mock_svc.list_events.assert_called_once_with(
            "pipeline-1",
            after_sequence=2,
        )

    def test_task_result_uses_canonical_artifact_contract(self, client):
        from src.core.artifacts import ArtifactRecord

        task_svc = MagicMock()
        task_svc.get_task.return_value = TaskStatus(
            task_id="pipeline-result",
            state="completed",
            progress=1.0,
        )
        artifact_svc = MagicMock()
        artifact_svc.get_task_result_view.return_value = {
            "task_id": "pipeline-result",
            "primary_artifact_id": "artifact-2",
            "artifacts": [
                ArtifactRecord(
                    artifact_id="artifact-1",
                    task_id="pipeline-result",
                    artifact_type="subtitle.srt",
                    path="/output/subtitle.srt",
                    preview_kind="subtitle",
                ),
                ArtifactRecord(
                    artifact_id="artifact-2",
                    task_id="pipeline-result",
                    artifact_type="audio.mix",
                    path="/output/final.wav",
                    preview_kind="audio",
                    is_primary=True,
                ),
            ],
            "warnings": [],
        }
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(task_svc)
        client.app.dependency_overrides[dependencies.artifact_service] = _mock_dep(artifact_svc)

        resp = client.get("/api/v1/tasks/pipeline-result/result")

        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {
            "task_id",
            "primary_artifact_id",
            "artifacts",
            "warnings",
        }
        assert data["primary_artifact_id"] == "artifact-2"
        assert data["artifacts"][0]["type"] == "subtitle.srt"
        assert data["artifacts"][0]["preview"] is True
        assert data["artifacts"][0]["primary"] is False
        assert data["artifacts"][1]["primary"] is True
        assert "primary_output" not in data
        assert "files" not in data
