from __future__ import annotations

from unittest.mock import MagicMock

from src.app.services.preset_catalog_service import PresetCatalogService
from src.app.services.pipeline_service import PipelineService
from src.core.orchestration.pipeline.graph_validation import validate_graph


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


def test_only_selected_builtin_graphs_remain_and_old_definitions_are_not_recoverable(tmp_path):
    service = PresetCatalogService(user_presets_path=tmp_path / "flow_presets.json")
    catalog = service.list_presets()
    assert service.list_archived_presets() == []
    assert [preset["id"] for preset in catalog] == [
        "custom_07458dd97f9e467eb6aef34d499923a5",
        "custom_964998d159ec4c30a5cc6bf44b76caeb",
    ]
    assert [preset["label"] for preset in catalog] == ["ASMR正常流程", "TTS配音"]
    assert [preset["revision"] for preset in catalog] == [2, 1]
    assert all(preset["builtin"] and preset["version"] == 2 for preset in catalog)
    assert {
        preset["id"]: [node["kind"] for node in preset["graph"]["nodes"]]
        for preset in catalog
    } == {
        "custom_07458dd97f9e467eb6aef34d499923a5": [
            "separate", "asr", "align", "translate", "tts", "mix", "export",
        ],
        "custom_964998d159ec4c30a5cc6bf44b76caeb": ["tts", "mix"],
    }


def test_active_builtin_graphs_are_valid_and_preserve_their_revisions(tmp_path):
    presets = PresetCatalogService(user_presets_path=tmp_path / "flow_presets.json").list_presets()
    revisions = {
        "custom_07458dd97f9e467eb6aef34d499923a5": 2,
        "custom_964998d159ec4c30a5cc6bf44b76caeb": 1,
    }
    assert len(presets) == 2

    for preset in presets:
        assert preset["label"].strip()
        assert isinstance(preset["description"], str)
        assert preset["builtin"] and preset["revision"] == revisions[preset["id"]]
        assert preset["version"] == 2
        validated = validate_graph(preset["graph"], template=True)
        assert validated["nodes"] == preset["graph"]["nodes"]
        assert validated["edges"] == preset["graph"]["edges"]
        assert [(item["node_id"], item["port"]) for item in validated["outputs"]] == [
            (item["node_id"], item["port"]) for item in preset["graph"]["outputs"]
        ]


def test_pipeline_service_keeps_preset_catalog_compatibility():
    assert _make_pipeline_service().list_presets() == PresetCatalogService().list_presets()
