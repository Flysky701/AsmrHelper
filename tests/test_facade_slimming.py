"""Tests for Phase 2B+2D: ModelManager deprecation and facade slimming.

Verifies:
- ModelService uses engine registries (no ModelManager import)
- ModelManager emits DeprecationWarning
- Facade services delegate to engine runtimes (no legacy class imports)
- AudioToolService dispatches by tool name
"""

from __future__ import annotations

import importlib
import sys
import warnings
from unittest.mock import MagicMock, patch

import pytest


class TestModelManagerDeprecation:
    """Verify ModelManager emits DeprecationWarning."""

    def test_get_model_manager_emits_warning(self):
        # Clear cached singleton
        import src.core.model_manager as mm_module
        old_manager = mm_module._manager
        mm_module._manager = None
        try:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                from src.core.model_manager import get_model_manager
                mgr = get_model_manager()
                dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
                assert len(dep_warnings) >= 1
                assert "deprecated" in str(dep_warnings[0].message).lower()
                assert mgr is not None
        finally:
            mm_module._manager = old_manager

    def test_model_manager_instantiation_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.core.model_manager import ModelManager
            mgr = ModelManager()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "engine registries" in str(dep_warnings[0].message).lower()


class TestModelServiceNoModelManager:
    """Verify ModelService does not import ModelManager."""

    def test_no_model_manager_import_in_source(self):
        import inspect
        from src.app.services.model_service import ModelService
        source = inspect.getsource(ModelService)
        assert "model_manager" not in source.lower().replace("_model_manager", "")
        assert "get_model_manager" not in source

    def test_unload_uses_registry(self):
        from src.app.services.model_service import ModelService

        mock_core = MagicMock()
        mock_entry = MagicMock()
        mock_entry.category = "tts"
        mock_entry.provider = "edge"
        mock_entry.id = "edge-tts"
        mock_core.get_model.return_value = mock_entry
        mock_core.get_status.return_value = MagicMock(model_id="edge-tts", status="unloaded", detail="")

        service = ModelService(core_service=mock_core)

        mock_registry = MagicMock()
        with patch("src.app.services.model_service.ModelService._get_registry", return_value=mock_registry):
            result = service.unload_model("edge-tts")

        mock_registry.unload.assert_called_once_with("edge")
        assert result.action == "unload"
        assert result.success is True


class TestTranslationServiceRemoved:
    """Verify TranslationService has been removed in favor of LlmCapabilityService."""

    def test_translation_service_module_removed(self):
        """TranslationService facade should no longer exist."""
        import os
        assert not os.path.exists("src/app/services/translation_service.py")

    def test_llm_capability_service_is_primary(self):
        """LlmCapabilityService should be the primary translation service."""
        from src.app.services import LlmCapabilityService
        assert LlmCapabilityService is not None


class TestAsrServiceRemoved:
    """Verify AsrService facade has been removed in favor of AsrEngineService."""

    def test_asr_service_module_removed(self):
        """AsrService facade should no longer exist."""
        import os
        assert not os.path.exists("src/app/services/asr_service.py")

    def test_asr_engine_service_is_primary(self):
        """AsrEngineService should be the primary ASR service."""
        from src.app.services import AsrEngineService
        assert AsrEngineService is not None


class TestTtsServiceRemoved:
    """Verify TtsService facade has been removed in favor of TtsEngineService."""

    def test_tts_service_module_removed(self):
        """TtsService facade should no longer exist."""
        import os
        assert not os.path.exists("src/app/services/tts_service.py")

    def test_tts_engine_service_is_primary(self):
        """TtsEngineService should be the primary TTS service."""
        from src.app.services import TtsEngineService
        assert TtsEngineService is not None


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

    def test_no_legacy_imports(self):
        source_code = open(
            "src/app/services/audio_tool_service.py", encoding="utf-8"
        ).read()
        assert "from src.core.translate import Translator" not in source_code
        assert "from src.core.asr import ASRRecognizer" not in source_code
        assert "from src.core.tts import TTSEngine" not in source_code
