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


class TestTranslationServiceSlimmed:
    """Verify TranslationService has no legacy Translator import."""

    def test_no_translator_import(self):
        import inspect
        from src.app.services.translation_service import TranslationService
        source = inspect.getsource(sys.modules["src.app.services.translation_service"])
        # Should not have "from src.core.translate import Translator"
        assert "from src.core.translate import Translator" not in source

    def test_delegates_to_llm_service(self, tmp_path):
        from src.app.services.translation_service import TranslationService

        input_file = tmp_path / "input.txt"
        input_file.write_text("line1\nline2\n", encoding="utf-8")

        mock_llm_svc = MagicMock()
        mock_llm_svc.translate_texts.return_value = MagicMock(
            items=["翻译1", "翻译2"],
            provider="deepseek",
            source_lang="ja",
            target_lang="zh",
        )

        service = TranslationService(llm_service=mock_llm_svc)
        result = service.translate_file(str(input_file), provider="deepseek")

        mock_llm_svc.translate_texts.assert_called_once()


class TestAsrServiceSlimmed:
    """Verify AsrService has no legacy ASRRecognizer import."""

    def test_no_asr_recognizer_import(self):
        source_code = open(
            "src/app/services/asr_service.py", encoding="utf-8"
        ).read()
        assert "from src.core.asr import ASRRecognizer" not in source_code
        assert "ASRRecognizer" not in source_code

    def test_delegates_to_engine_service(self):
        from src.app.services.asr_service import AsrService

        mock_engine_svc = MagicMock()
        mock_engine_svc.transcribe_file.return_value = MagicMock(
            segments=[], output_path=None, text=""
        )

        service = AsrService(engine_service=mock_engine_svc)
        service.transcribe_file("/fake/audio.wav")

        mock_engine_svc.transcribe_file.assert_called_once()


class TestTtsServiceSlimmed:
    """Verify TtsService has no legacy TTSEngine import."""

    def test_no_tts_engine_import(self):
        source_code = open(
            "src/app/services/tts_service.py", encoding="utf-8"
        ).read()
        assert "from src.core.tts import TTSEngine" not in source_code

    def test_delegates_to_engine_service(self, tmp_path):
        from src.app.services.tts_service import TtsService

        input_file = tmp_path / "text.txt"
        input_file.write_text("hello", encoding="utf-8")

        mock_engine_svc = MagicMock()
        mock_engine_svc.synthesize_text.return_value = MagicMock(
            engine="edge", voice="zh-CN-XiaoxiaoNeural", output_path="/out.wav"
        )

        service = TtsService(engine_service=mock_engine_svc)
        service.synthesize_file(str(input_file), "/out.wav")

        mock_engine_svc.synthesize_text.assert_called_once()


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
