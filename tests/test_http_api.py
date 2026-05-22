"""Tests for the FastAPI HTTP API layer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.http.app import create_app
from src.api.http import dependencies
from src.app.dto import (
    ArtifactSet,
    ModelOperationResult,
    ModelStatusView,
    ModelSummary,
    ModelVerificationResult,
    PipelineResult,
    ResourceStatus,
    SubtitleSegment,
    SynthesisResult,
    TaskStatus,
    TranscriptionResult,
    TranslationResult,
)
from src.app.errors import (
    AppError,
    AppExecutionError,
    AppValidationError,
    ResourceUnavailableError,
    ResourceValidationError,
)


@pytest.fixture()
def client():
    app = create_app()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _mock_dep(mock_obj):
    """Return a lambda that returns the mock, suitable for dependency override."""
    return lambda: mock_obj


# ─── Health ───────────────────────────────────────────────────────────


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ─── Pipeline ─────────────────────────────────────────────────────────


class TestPipelineRoutes:
    def test_list_presets(self, client):
        mock_svc = MagicMock()
        mock_svc.list_presets.return_value = {
            "asmr_bilingual": "Bilingual pipeline",
            "asr_only": "ASR only",
        }
        client.app.dependency_overrides[dependencies.pipeline_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/pipeline/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "asmr_bilingual" in data["presets"]
        assert "asr_only" in data["presets"]
        mock_svc.list_presets.assert_called_once_with()

    def test_run_pipeline_success(self, client):
        mock_svc = MagicMock()
        mock_svc.run_audio_pipeline.return_value = PipelineResult(
            success=True,
            input_path="/test/input.wav",
            task=TaskStatus(task_id="pipeline-1", state="completed", progress=1.0),
            task_id="pipeline-1",
            task_state="completed",
            artifacts=ArtifactSet(
                files={
                    "mix": "/test/output/mix.wav",
                    "subtitle": "/test/output/subtitle.srt",
                },
                primary_output="/test/output/mix.wav",
            ),
            mix_path="/test/output/mix.wav",
            total_duration=12.5,
        )
        client.app.dependency_overrides[dependencies.pipeline_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/pipeline/run",
            json={
                "input_path": "/test/input.wav",
                "vtt_path": "/test/input.vtt",
                "use_vocal_separator": False,
                "tts_speed": 1.1,
                "original_volume": 0.9,
                "tts_volume_ratio": 0.6,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["task_id"] == "pipeline-1"
        assert data["task"]["task_id"] == "pipeline-1"
        assert data["task"]["state"] == "completed"
        assert data["artifacts"]["primary_output"] == "/test/output/mix.wav"
        assert data["artifacts"]["files"]["subtitle"] == "/test/output/subtitle.srt"
        assert data["mix_path"] == "/test/output/mix.wav"
        request = mock_svc.run_audio_pipeline.call_args.args[0]
        assert request.vtt_path == "/test/input.vtt"
        assert request.use_vocal_separator is False
        assert request.tts_speed == 1.1
        assert request.original_volume == 0.9
        assert request.tts_volume_ratio == 0.6

    def test_run_pipeline_validation_error(self, client):
        mock_svc = MagicMock()
        mock_svc.run_audio_pipeline.side_effect = AppValidationError("input_path is required")
        client.app.dependency_overrides[dependencies.pipeline_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/pipeline/run",
            json={"input_path": ""},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_run_pipeline_missing_field(self, client):
        resp = client.post("/api/v1/pipeline/run", json={})
        assert resp.status_code == 422


# ─── ASR ──────────────────────────────────────────────────────────────


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

    def test_transcribe_validation_error(self, client):
        mock_svc = MagicMock()
        mock_svc.transcribe_file.side_effect = AppValidationError("file not found")
        client.app.dependency_overrides[dependencies.asr_engine_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/asr/transcribe",
            json={"input_path": "/nonexistent.wav"},
        )
        assert resp.status_code == 400


# ─── Translation ──────────────────────────────────────────────────────


class TestTranslationRoutes:
    def test_translate_success(self, client):
        mock_svc = MagicMock()
        mock_svc.translate_file.return_value = TranslationResult(
            items=["你好", "世界"],
            provider="deepseek",
            source_lang="ja",
            target_lang="zh",
        )
        client.app.dependency_overrides[dependencies.translation_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/translation/translate",
            json={"input_path": "/test/text.txt"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == ["你好", "世界"]
        assert data["provider"] == "deepseek"


# ─── TTS ──────────────────────────────────────────────────────────────


class TestTtsRoutes:
    def test_list_tts_engines(self, client):
        mock_svc = MagicMock()
        mock_svc.list_engines.return_value = [
            {
                "category": "tts",
                "provider": "kokoro",
                "display_name": "Kokoro TTS",
                "kind": "local",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    {"name": "voice", "type": "string", "required": False, "default": "af_heart", "description": ""},
                ],
                "provider_option_schema": [
                    {"name": "lang_code", "type": "string", "required": False, "default": None, "description": ""},
                ],
                "supports": {"voice_list": True, "lightweight_local": True},
            }
        ]
        client.app.dependency_overrides[dependencies.tts_engine_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tts/engines")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines"][0]["provider"] == "kokoro"
        assert data["engines"][0]["common_option_schema"][0]["name"] == "voice"

    def test_synthesize_success(self, client, tmp_path):
        mock_svc = MagicMock()
        result_mock = MagicMock()
        result_mock.engine = "kokoro"
        result_mock.voice = "af_heart"
        result_mock.output_path = "/test/output.wav"
        mock_svc.synthesize_text.return_value = result_mock
        client.app.dependency_overrides[dependencies.tts_engine_service] = _mock_dep(mock_svc)

        # Create a real input file since the route checks existence
        input_file = tmp_path / "text.txt"
        input_file.write_text("hello world", encoding="utf-8")

        resp = client.post(
            "/api/v1/tts/synthesize",
            json={
                "input_path": str(input_file),
                "output_path": "/test/output.wav",
                "engine": "kokoro",
                "model": "default",
                "voice": "af_heart",
                "speed": 1.1,
                "provider_options": {"lang_code": "a"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "kokoro"
        assert data["output_path"] == "/test/output.wav"
        mock_svc.synthesize_text.assert_called_once_with(
            text="hello world",
            output_path="/test/output.wav",
            provider="kokoro",
            model="default",
            common_options={"voice": "af_heart", "speed": 1.1},
            provider_options={"lang_code": "a"},
        )


# ─── Models ───────────────────────────────────────────────────────────


class TestModelRoutes:
    def test_list_models(self, client):
        mock_svc = MagicMock()
        mock_svc.list_models.return_value = [
            ModelSummary(
                model_id="whisper-base",
                kind="local",
                category="asr",
                backend="faster_whisper",
                display_name="Whisper Base",
            ),
        ]
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["model_id"] == "whisper-base"
        assert data[0]["family_id"] is None
        assert data[0]["install_modes"] == []

    def test_get_model_status(self, client):
        mock_svc = MagicMock()
        mock_svc.get_model_status.return_value = ModelStatusView(
            model_id="whisper-base",
            status="installed",
            detail="all files present",
        )
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/models/whisper-base/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "installed"

    def test_install_model(self, client):
        mock_svc = MagicMock()
        mock_svc.install_model.return_value = ModelOperationResult(
            action="install",
            model_id="whisper-base",
            success=True,
            status="installed",
            detail="downloaded successfully",
        )
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/models/whisper-base/install",
            json={
                "install_mode": "recommended",
                "install_dependencies": False,
                "install_recommended_assets": True,
                "allow_fallback_variant": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        mock_svc.install_model.assert_called_once_with(
            "whisper-base",
            mirror=None,
            force=False,
            install_mode="recommended",
            install_dependencies=False,
            install_recommended_assets=True,
            allow_fallback_variant=True,
        )

    def test_verify_model(self, client):
        mock_svc = MagicMock()
        mock_svc.verify_models.return_value = [
            ModelVerificationResult(
                model_id="whisper-base",
                success=True,
                status="installed",
                detail="all files verified",
            ),
        ]
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.post("/api/v1/models/whisper-base/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["success"] is True

    def test_remove_model(self, client):
        mock_svc = MagicMock()
        mock_svc.remove_model.return_value = ModelOperationResult(
            action="remove",
            model_id="whisper-base",
            success=True,
            status="missing",
            detail="removed",
        )
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.delete("/api/v1/models/whisper-base")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["action"] == "remove"


# ─── Subtitles ────────────────────────────────────────────────────────


class TestSubtitleRoutes:
    def test_load_subtitle_missing_file(self, client):
        resp = client.post(
            "/api/v1/subtitles/load",
            json={"file_path": "/nonexistent/test.srt"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_load_subtitle_returns_document_shape(self, client, tmp_path):
        subtitle_file = tmp_path / "test.srt"
        subtitle_file.write_text(
            "1\n00:00:00,000 --> 00:00:02,500\nHello\n",
            encoding="utf-8",
        )

        resp = client.post(
            "/api/v1/subtitles/load",
            json={"file_path": str(subtitle_file)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["document"]["segments"][0]["text"] == "Hello"
        assert data["segments"][0]["text"] == "Hello"

    def test_export_subtitle(self, client, tmp_path):
        mock_svc = MagicMock()
        mock_svc.export_document.return_value = str(tmp_path / "test.srt")
        client.app.dependency_overrides[dependencies.subtitle_service] = _mock_dep(mock_svc)

        output_file = str(tmp_path / "test.srt")
        resp = client.post(
            "/api/v1/subtitles/export",
            json={
                "segments": [{"start": 0.0, "end": 2.5, "text": "Hello"}],
                "output_path": output_file,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["segment_count"] == 1

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


# ─── Resources ────────────────────────────────────────────────────────


class TestResourceRoutes:
    def test_resource_status(self, client):
        mock_svc = MagicMock()
        mock_svc.check_required_resources.return_value = [
            ResourceStatus(name="project_root", available=True, detail="ready"),
            ResourceStatus(name="output_dir", available=True, detail="ready"),
            ResourceStatus(name="models_dir", available=True, detail="ready"),
        ]
        client.app.dependency_overrides[dependencies.resource_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/resources/status")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["resources"]) == 3


# ─── Tasks ────────────────────────────────────────────────────────────


class TestTaskRoutes:
    def test_list_tasks(self, client):
        mock_svc = MagicMock()
        mock_svc.list_tasks.return_value = [
            TaskStatus(task_id="pipeline-1", state="completed", progress=1.0),
        ]
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_id"] == "pipeline-1"

    def test_get_task(self, client):
        mock_svc = MagicMock()
        mock_svc.get_task.return_value = TaskStatus(
            task_id="pipeline-1", state="running", progress=0.5, message="processing"
        )
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tasks/pipeline-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "running"
        assert data["progress"] == 0.5

    def test_get_task_not_found(self, client):
        mock_svc = MagicMock()
        mock_svc.get_task.side_effect = AppValidationError("unknown task id: bad-id")
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tasks/bad-id")
        assert resp.status_code == 400


# ─── Error Handling ───────────────────────────────────────────────────


class TestErrorHandling:
    def test_resource_not_found(self, client):
        mock_svc = MagicMock()
        mock_svc.get_model_status.side_effect = ResourceUnavailableError("model not found")
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/models/nonexistent/status")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_execution_error(self, client):
        mock_svc = MagicMock()
        mock_svc.install_model.side_effect = AppExecutionError("download failed")
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.post("/api/v1/models/whisper-base/install")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "EXECUTION_ERROR"

    def test_resource_validation_error(self, client):
        mock_svc = MagicMock()
        mock_svc.check_required_resources.side_effect = ResourceValidationError("invalid workspace")
        client.app.dependency_overrides[dependencies.resource_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/resources/status")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "RESOURCE_INVALID"
