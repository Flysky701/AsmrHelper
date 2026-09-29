"""Model unloading and unsupported audio-tool behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestModelServiceUnload:
    """Verify model unloading delegates to the selected engine registry."""


    def test_tts_unload_uses_speech_provider(self):
        from src.app.services.model_service import ModelService

        mock_core = MagicMock()
        mock_entry = MagicMock()
        mock_entry.category = "tts"
        mock_entry.provider = "edge"
        mock_entry.id = "edge-tts"
        mock_core.get_model.return_value = mock_entry
        mock_core.get_status.return_value = MagicMock(
            model_id="edge-tts", status="unloaded", detail=""
        )

        service = ModelService(core_service=mock_core)

        mock_provider = MagicMock()
        with patch(
            "src.core.speech.providers.get_provider", return_value=mock_provider
        ):
            result = service.unload_model("edge-tts")

        mock_provider.release.assert_called_once_with()
        assert result.action == "unload"
        assert result.success is True


class TestAudioToolServiceDispatch:
    """Verify AudioToolService dispatches by tool name."""

    def test_unsupported_tool_raises(self):
        from src.app.errors import AppValidationError
        from src.app.services.audio_tool_service import AudioToolService

        service = AudioToolService()
        mock_task_spec = MagicMock()
        mock_task_spec.task_type = "tool.nonexistent"
        mock_task_spec.task_id = "test-1"
        mock_task_spec.session_id = "s1"
        mock_task_spec.input_asset_id = "a1"

        # Mock dependencies
        service._session_service = MagicMock()
        service._session_service.get_session.return_value = MagicMock(resolved_output_dir="/tmp")
        service._input_catalog_service = MagicMock()
        service._input_catalog_service.get_asset.return_value = MagicMock(absolute_path="/fake.wav")
        service._task_service = MagicMock()

        with pytest.raises(AppValidationError, match="unsupported tool"):
            service.run_tool_task_spec(mock_task_spec)
