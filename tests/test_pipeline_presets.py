from __future__ import annotations

from unittest.mock import MagicMock

from src.app.services.preset_catalog_service import PresetCatalogService
from src.app.services.pipeline_service import PipelineService
from src.core.orchestration.pipeline.graph_validation import validate_graph


ALLOWED_PRESET_STAGES = {
    "separate",
    "asr",
    "translate",
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


def test_retired_builtin_definitions_remain_recoverable_without_active_defaults(tmp_path):
    service = PresetCatalogService(user_presets_path=tmp_path / "flow_presets.json")
    assert service.list_presets() == []
    catalog = service.list_archived_presets()
    presets = [preset for preset in catalog if preset.get("version") != 2]

    assert [preset["id"] for preset in presets] == [
        "audio_subtitles", "subtitle_translation", "subtitle_speech", "audio_translation_speech",
        "asmr_bilingual", "asr_only",
    ]
    assert {preset["id"]: preset["stages"] for preset in presets} == {
        "audio_subtitles": ["asr", "export"],
        "subtitle_translation": ["translate", "export"],
        "subtitle_speech": ["tts"],
        "audio_translation_speech": ["asr", "translate", "tts", "export"],
        "asmr_bilingual": [
            "separate",
            "asr",
            "translate",
            "tts",
            "mix",
            "export",
        ],
        "asr_only": ["asr", "export"],
    }
    assert {
        preset["id"]: [node["kind"] for node in preset["graph"]["nodes"]]
        for preset in catalog if preset.get("version") == 2
    } == {
        "graph_audio_subtitles": ["asr", "export"],
        "graph_subtitle_translation": ["translate", "export"],
        "graph_subtitle_speech": ["tts"],
        "graph_audio_translation_speech": ["asr", "translate", "tts", "export"],
    }


def test_archived_builtin_stages_are_known_unique_and_described(tmp_path):
    presets = PresetCatalogService(user_presets_path=tmp_path / "flow_presets.json").list_archived_presets()

    for preset in presets:
        assert preset["label"].strip()
        assert preset["description"].strip()
        assert preset["builtin"] and preset["revision"] == 1
        if preset.get("version") == 2:
            assert validate_graph(preset["graph"], template=True) == preset["graph"]
            continue
        assert preset["stages"]
        assert len(preset["stages"]) == len(set(preset["stages"]))
        assert set(preset["stages"]) <= ALLOWED_PRESET_STAGES
        assert preset["outputs"] and set(preset["outputs"]) <= set(preset["stages"])


def test_pipeline_service_keeps_preset_catalog_compatibility():
    assert _make_pipeline_service().list_presets() == PresetCatalogService().list_presets()
