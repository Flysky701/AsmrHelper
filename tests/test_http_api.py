"""Tests for the FastAPI HTTP API layer."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.http.app import create_app
from src.api.http import dependencies
from src.app.dto import (
    ModelOperationResult,
    ModelStatusView,
    ModelStatusIssueView,
    ModelSummary,
    ModelVerificationResult,
    ResourceStatus,
    TaskStatus,
    TranslationResult,
)
from src.app.errors import (
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


# ─── Pipeline ─────────────────────────────────────────────────────────


class TestPipelineRoutes:
    def test_list_presets(self, client):
        mock_svc = MagicMock()
        mock_svc.list_presets.return_value = [
            {"id": "asmr_bilingual", "label": "ASMR Bilingual", "description": "Full pipeline", "stages": ["asr", "tts"]},
            {"id": "asr_only", "label": "ASR Only", "description": "ASR only", "stages": ["asr"]},
        ]
        client.app.dependency_overrides[dependencies.preset_catalog_service] = _mock_dep(
            mock_svc
        )

        resp = client.get("/api/v1/pipeline/presets")
        assert resp.status_code == 200
        data = resp.json()
        ids = [p["id"] for p in data["presets"]]
        assert "asmr_bilingual" in ids
        assert "asr_only" in ids
        assert data["presets"][0]["label"] == "ASMR Bilingual"
        mock_svc.list_presets.assert_called_once_with()

    def test_list_presets_does_not_initialize_pipeline_runtime(self, client, monkeypatch):
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
            "asmr_bilingual",
            "asr_only",
        ]

    def test_legacy_pipeline_routes_are_removed(self, client):
        assert client.post("/api/v1/pipeline/run", json={}).status_code == 404
        assert client.post("/api/v1/pipeline/tasks", json={}).status_code == 404


class TestPipelineRunRoutes:
    def test_submit_v1_pipeline_run_preserves_stage_profiles(self, client):
        mock_svc = MagicMock()
        mock_svc.submit_task.return_value = TaskStatus(
            task_id="pipeline-1",
            task_type="pipeline",
            state="pending",
            progress=0.0,
            created_at="2026-07-23T10:00:00+00:00",
        )
        client.app.dependency_overrides[
            dependencies.pipeline_task_orchestrator
        ] = _mock_dep(mock_svc)
        profile = {
            "version": 1,
            "source_lang": "ja",
            "target_lang": "zh",
            "skip_existing": True,
            "stages": {
                "separate": {
                    "enabled": False,
                    "provider": "demucs",
                    "model": "htdemucs",
                    "options": {"mode": "vocals"},
                    "provider_options": {},
                },
                "asr": {
                    "enabled": True,
                    "provider": "faster_whisper",
                    "model": "faster-whisper-base",
                    "options": {"language": "ja"},
                    "provider_options": {"vad_filter": False},
                },
                "translate": {
                    "enabled": True,
                    "provider": "deepseek",
                    "model": None,
                    "options": {"target_lang": "zh"},
                    "provider_options": {},
                },
                "tts": {
                    "enabled": True,
                    "provider": "edge",
                    "model": None,
                    "options": {"voice": "zh-CN-XiaoxiaoNeural"},
                    "provider_options": {},
                },
                "mix": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {"tts_delay_ms": 250},
                    "provider_options": {},
                },
                "export": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {"subtitle_format": "srt"},
                    "provider_options": {},
                },
            },
        }

        resp = client.post(
            "/api/v1/pipeline-runs",
            json={
                "input": {
                    "path": "/test/input.wav",
                    "companion_paths": ["/test/input.vtt"],
                },
                "output": {"directory": "/test/output"},
                "execution_profile": profile,
            },
        )

        assert resp.status_code == 202
        request = mock_svc.submit_task.call_args.args[0]
        assert request.input_path == "/test/input.wav"
        assert request.output_dir == "/test/output"
        assert request.companion_paths == ["/test/input.vtt"]
        assert request.execution_profile == profile
        assert "profiles" not in request.execution_profile

    def test_submit_pipeline_run_rejects_legacy_flat_request(self, client):
        mock_svc = MagicMock()
        client.app.dependency_overrides[
            dependencies.pipeline_task_orchestrator
        ] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/pipeline-runs",
            json={
                "input_path": "/test/input.wav",
                "source_lang": "ja",
                "target_lang": "zh",
                "tts_engine": "edge",
            },
        )

        assert resp.status_code == 422
        mock_svc.submit_task.assert_not_called()

    def test_submit_pipeline_run_requires_input(self, client):
        resp = client.post("/api/v1/pipeline-runs", json={})
        assert resp.status_code == 422

    def test_default_pipeline_profile_uses_demucs_provider(self, client):
        mock_svc = MagicMock()
        mock_svc.submit_task.return_value = TaskStatus(
            task_id="pipeline-defaults",
            task_type="pipeline",
            state="pending",
            progress=0.0,
            created_at="2026-07-28T10:00:00+00:00",
        )
        client.app.dependency_overrides[
            dependencies.pipeline_task_orchestrator
        ] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/pipeline-runs",
            json={"input": {"path": "/test/input.wav"}},
        )

        assert resp.status_code == 202
        profile = mock_svc.submit_task.call_args.args[0].execution_profile
        assert profile["stages"]["separate"]["provider"] == "demucs"
        assert profile["stages"]["separate"]["model"] == "htdemucs"

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/pipeline-runs/start",
            "/api/v1/pipeline-runs/execute",
            "/api/v1/tool-runs",
        ],
    )
    def test_replaced_manual_execution_routes_are_unavailable(self, client, path):
        resp = client.post(path, json={"task_id": "obsolete-task"})
        assert resp.status_code in {404, 405}

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
            "/api/v1/tool-runs/tasks",
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

    def test_legacy_sync_tool_route_is_removed(self, client):
        resp = client.post(
            "/api/v1/tools/convert",
            json={
                "input_path": "/test/input.wav",
                "output_path": "/test/output.wav",
            },
        )

        assert resp.status_code == 404


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


# ─── Translation (via LLM) ────────────────────────────────────────────


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

    def test_list_tts_voices(self, client):
        mock_svc = MagicMock()
        mock_svc.list_voices.return_value = [
            {
                "id": "zh-CN-XiaoxiaoNeural",
                "name": "晓晓（女）",
                "language": "zh-CN",
            }
        ]
        client.app.dependency_overrides[dependencies.tts_engine_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/tts/engines/edge/voices")

        assert resp.status_code == 200
        assert resp.json() == {
            "engine_id": "edge",
            "voices": [
                {
                    "id": "zh-CN-XiaoxiaoNeural",
                    "name": "晓晓（女）",
                    "language": "zh-CN",
                }
            ],
        }
        mock_svc.list_voices.assert_called_once_with("edge")

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


# ─── Capabilities ─────────────────────────────────────────────────────


class TestCapabilityRoutes:
    def test_option_schema_exposes_stable_constraint_fields(self, client):
        resp = client.get(
            "/api/v1/capabilities",
            params={"category": "asr", "provider": "faster_whisper"},
        )

        assert resp.status_code == 200
        option = resp.json()[0]["provider_option_schema"][0]
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


# ─── Settings ─────────────────────────────────────────────────────────


class TestSettingsRoutes:
    def test_get_uses_public_settings_envelope(self, client):
        mock_svc = MagicMock()
        mock_svc.get_settings.return_value = {
            "providers": {
                "default_llm": "deepseek",
                "deepseek": {
                    "base_url": "https://api.deepseek.com",
                    "credential_configured": True,
                },
            }
        }
        client.app.dependency_overrides[dependencies.settings_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/settings")

        assert resp.status_code == 200
        assert resp.json()["settings"]["providers"]["deepseek"]["credential_configured"] is True
        mock_svc.get_settings.assert_called_once_with(masked=True)

    def test_put_passes_settings_envelope_to_service(self, client):
        mock_svc = MagicMock()
        mock_svc.update_settings.return_value = {
            "providers": {"default_llm": "openai"}
        }
        client.app.dependency_overrides[dependencies.settings_service] = _mock_dep(mock_svc)
        settings = {
            "providers": {
                "default_llm": "openai",
                "openai": {"credential": "new-key"},
            }
        }

        resp = client.put("/api/v1/settings", json={"settings": settings})

        assert resp.status_code == 200
        mock_svc.update_settings.assert_called_once_with(settings)

    def test_provider_test_returns_stable_result(self, client):
        from src.app.services.settings_service import ProviderTestResult

        mock_svc = MagicMock()
        mock_svc.test_provider.return_value = ProviderTestResult(
            provider="deepseek",
            success=False,
            error_code="PROVIDER_CONNECTION_FAILED",
            message="Provider 连接或鉴权失败",
        )
        client.app.dependency_overrides[dependencies.settings_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/settings/test-provider",
            json={
                "provider": "deepseek",
                "settings": {
                    "providers": {
                        "deepseek": {
                            "credential": "candidate",
                            "base_url": "https://api.deepseek.com",
                        }
                    }
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json()["error_code"] == "PROVIDER_CONNECTION_FAILED"
        assert resp.json()["success"] is False


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
                install_strategy="whisper",
            ),
        ]
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["model_id"] == "whisper-base"
        assert data[0]["install_strategy"] == "whisper"
        assert data[0]["family_id"] is None
        assert data[0]["install_modes"] == []

    def test_get_model_status(self, client):
        mock_svc = MagicMock()
        mock_svc.get_model_status.return_value = ModelStatusView(
            model_id="whisper-base",
            status="installed",
            detail="all files present",
            executable=False,
            issues=[
                ModelStatusIssueView(
                    code="PYTHON_DEPENDENCY_MISSING",
                    requirement="faster_whisper",
                    message="Python dependency is unavailable: faster_whisper",
                )
            ],
        )
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/models/whisper-base/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "installed"
        assert data["executable"] is False
        assert data["issues"][0]["code"] == "PYTHON_DEPENDENCY_MISSING"

    def test_install_model_sync(self, client):
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
            "/api/v1/models/whisper-base/install?sync=true",
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

    def test_install_model_async(self, client):
        mock_svc = MagicMock()
        mock_svc.install_model_async.return_value = TaskStatus(
            task_id="model_install-1",
            task_type="model_install",
            task_source="api",
            state="running",
            stage="install",
            progress=0.1,
            created_at="2026-08-07T00:00:00+00:00",
        )
        client.app.dependency_overrides[dependencies.model_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/models/whisper-base/install",
            json={"install_mode": "single"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["task_id"] == "model_install-1"
        assert data["state"] == "running"
        assert data["task_type"] == "model_install"
        mock_svc.install_model_async.assert_called_once()

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


class TestVoiceTaskRoutes:
    @pytest.mark.parametrize(
        ("path", "method_name", "payload", "task_type"),
        [
            ("/api/v1/voice/design", "submit_design_voice", {"name": "voice", "description": "warm"}, "voice.design"),
            ("/api/v1/voice/clone", "submit_clone_voice", {"name": "voice", "audio_path": "input.wav"}, "voice.clone"),
            ("/api/v1/voice/profiles/A1/preview", "submit_preview_voice", {"text": "hello", "speed": 1.0}, "voice.preview"),
        ],
    )
    def test_voice_long_operations_return_task_snapshot(
        self, client, path, method_name, payload, task_type
    ):
        mock_svc = MagicMock()
        getattr(mock_svc, method_name).return_value = TaskStatus(
            task_id=f"{task_type}-1",
            task_type=task_type,
            task_source="voice-lab",
            state="running",
            stage=task_type.split(".")[-1],
            progress=0.1,
            created_at="2026-08-07T00:00:00+00:00",
        )
        client.app.dependency_overrides[dependencies.voice_service] = _mock_dep(mock_svc)

        response = client.post(path, json=payload)

        assert response.status_code == 201
        assert response.json()["task_type"] == task_type
        getattr(mock_svc, method_name).assert_called_once()


class TestSubtitleRoutes:
    def test_create_script_to_vtt_task_submits_background_work(self, client):
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
            "/api/v1/subtitles/script-to-vtt/tasks",
            json={"script_path": "script.txt", "fmt": "vtt"},
        )

        assert response.status_code == 201
        assert response.json()["task_id"] == "subtitle.script_to_vtt-1"
        assert response.json()["state"] == "running"
        request = mock_svc.create_task.call_args.args[0]
        assert request.script_path == "script.txt"
        assert request.fmt == "vtt"

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

    def test_bilingualize_subtitle_registers_artifact(self, client, tmp_path):
        output_path = str(tmp_path / "bilingual.srt")
        mock_svc = MagicMock()
        mock_svc.bilingualize_segments.return_value = output_path
        mock_artifacts = MagicMock()
        client.app.dependency_overrides[dependencies.subtitle_service] = _mock_dep(mock_svc)
        client.app.dependency_overrides[dependencies.artifact_service] = _mock_dep(mock_artifacts)

        resp = client.post(
            "/api/v1/subtitles/bilingualize",
            json={
                "segments": [
                    {
                        "start": 0,
                        "end": 1.25,
                        "text": "hello",
                        "translation": "你好",
                    }
                ],
                "output_path": output_path,
                "task_id": "task-bilingual",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["segment_count"] == 1
        assert mock_artifacts.register_artifact.call_args.kwargs["artifact_type"] == "subtitle.srt"


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

    def test_task_readiness_forwards_input_path(self, client):
        mock_svc = MagicMock()
        mock_svc.check_task_readiness.return_value = {
            "task_type": "pipeline",
            "ready": True,
            "missing_requirements": [],
            "issues": [],
            "execution_profile": {"stages": {}},
        }
        client.app.dependency_overrides[dependencies.resource_service] = _mock_dep(mock_svc)

        resp = client.post(
            "/api/v1/runtime/check-task-readiness",
            json={
                "task_type": "pipeline",
                "execution_profile": {"stages": {}},
                "input_path": "E:/audio/input.wav",
            },
        )

        assert resp.status_code == 200
        assert (
            mock_svc.check_task_readiness.call_args.kwargs["input_path"]
            == "E:/audio/input.wav"
        )


# ─── Tasks ────────────────────────────────────────────────────────────


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
        assert task_svc.get_task(task_id).state == "completed"

    def test_create_task_rejects_declared_type_without_callable(self, client):
        from src.api.http import dependencies
        from src.app.services.task_service import TaskService
        from src.core.tasks import ExecutorRegistry, TaskDispatcher

        registry = ExecutorRegistry()
        registry.register("declared.only")
        task_svc = TaskService(executor_registry=registry)
        dispatcher = TaskDispatcher(task_svc.registry, task_service=task_svc)
        client.app.dependency_overrides[dependencies.task_service] = _mock_dep(task_svc)
        client.app.dependency_overrides[dependencies.task_dispatcher] = _mock_dep(dispatcher)

        resp = client.post(
            "/api/v1/tasks",
            json={
                "task_type": "declared.only",
                "task_source": "http-test",
                "session_id": "session-1",
            },
        )

        assert resp.status_code == 400
        assert "no executable handler registered" in resp.json()["error"]["message"]
        assert task_svc.list_tasks() == []

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

        resp = client.post("/api/v1/models/whisper-base/install?sync=true")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "EXECUTION_ERROR"

    def test_resource_validation_error(self, client):
        mock_svc = MagicMock()
        mock_svc.check_required_resources.side_effect = ResourceValidationError("invalid workspace")
        client.app.dependency_overrides[dependencies.resource_service] = _mock_dep(mock_svc)

        resp = client.get("/api/v1/resources/status")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "RESOURCE_INVALID"
