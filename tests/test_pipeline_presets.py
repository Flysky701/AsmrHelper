from __future__ import annotations

from unittest.mock import MagicMock

from src.app.services.preset_catalog_service import PresetCatalogService
from src.app.services.pipeline_service import PipelineService


ALLOWED_PRESET_STAGES = {
    "separation",
    "asr",
    "translation",
    "tts",
    "mix",
    "export",
}


def _make_pipeline_service() -> PipelineService:
    return PipelineService(
        task_service=MagicMock(),
        resource_service=MagicMock(),
        workspace_service=MagicMock(),
        input_catalog_service=MagicMock(),
        session_service=MagicMock(),
        artifact_service=MagicMock(),
        executor=MagicMock(),
    )


def test_builtin_presets_expose_only_verified_closed_loops():
    presets = PresetCatalogService().list_presets()

    assert [preset["id"] for preset in presets] == ["asmr_bilingual", "asr_only"]
    assert {preset["id"]: preset["stages"] for preset in presets} == {
        "asmr_bilingual": [
            "separation",
            "asr",
            "translation",
            "tts",
            "mix",
            "export",
        ],
        "asr_only": ["asr", "export"],
    }


def test_builtin_preset_stages_are_known_unique_and_described():
    presets = PresetCatalogService().list_presets()

    for preset in presets:
        assert preset["label"].strip()
        assert preset["description"].strip()
        assert preset["stages"]
        assert len(preset["stages"]) == len(set(preset["stages"]))
        assert set(preset["stages"]) <= ALLOWED_PRESET_STAGES


def test_pipeline_service_keeps_preset_catalog_compatibility():
    assert _make_pipeline_service().list_presets() == PresetCatalogService().list_presets()
