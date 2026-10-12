from __future__ import annotations

from unittest.mock import MagicMock
from copy import deepcopy
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

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


def test_active_builtin_graphs_are_valid_and_preserve_their_revisions(tmp_path):
    presets = PresetCatalogService(user_presets_path=tmp_path / "flow_presets.json").list_presets()
    revisions = {
        "starter_edge_chinese_v1": 1,
        "custom_07458dd97f9e467eb6aef34d499923a5": 2,
        "custom_964998d159ec4c30a5cc6bf44b76caeb": 1,
    }
    assert len(presets) == 3

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


def test_starter_catalog_upgrade_is_read_only_and_deletion_is_durable(tmp_path):
    shipped = Path(__file__).resolve().parents[1] / "config" / "presets.yaml"
    old_path = tmp_path / "old-presets.yaml"
    definitions = yaml.safe_load(shipped.read_text(encoding="utf-8"))["presets"]
    old_path.write_text(yaml.safe_dump({"presets": definitions[1:]}), encoding="utf-8")
    user_path = tmp_path / "flow_presets.json"
    old = PresetCatalogService(old_path, user_path)
    custom = old.copy_preset(definitions[1]["id"], "用户自己的完整流程")
    old.delete_preset(definitions[2]["id"], 1)
    original = user_path.read_bytes()
    before = old.list_presets()

    # Reading new shipped data overlays exactly one starter without a migration
    # write, custom rewrite, or resurrection of a previously deleted builtin.
    new = PresetCatalogService(shipped, user_path)
    starter = new.list_presets()[0]
    assert starter["id"] == "starter_edge_chinese_v1"
    for _ in range(2):
        assert PresetCatalogService(shipped, user_path).list_presets() == [starter, *before]
        assert user_path.read_bytes() == original
    new.delete_preset(starter["id"], starter["revision"])
    assert PresetCatalogService(shipped, user_path).list_presets() == before
    assert next(item for item in new.list_presets() if item["id"] == custom["id"]) == custom


def test_starter_dependencies_and_mock_audio_through_real_graph(tmp_path, monkeypatch):
    """Use installed base dependencies, mocking only Edge audio generation.

    No HTTP, weight downloads, paid calls or local model inference. Real subtitle
    validation, speech compilation, timeline assembly and graph outputs execute.
    """
    from src.app.services import speech_service
    from src.app.services.graph_pipeline_service import (
        freeze_graph_connections, freeze_graph_speech, make_node_plan, prepare_graph_profile,
    )
    from src.app.services.resource_service import ResourceService
    from src.core.orchestration.pipeline.graph_executor import GraphExecutor
    from src.core.orchestration.pipeline.graph_validation import build_graph_plan
    from src.core.speech.compiler import compile_recipe
    from src.core.speech.store import SpeechStore, build_plan
    from src.utils import get_ffmpeg
    import subprocess

    speech = speech_service.SpeechService(store=SpeechStore(tmp_path / "speech"),
        tasks=MagicMock(), dispatcher=MagicMock(), artifacts=MagicMock())
    monkeypatch.setattr(speech_service, "get_speech_service", lambda: speech)
    # A user-selected named default must not redirect the starter to it.
    connection = speech.save_connection({"name": "用户连接", "provider_id": "edge",
                                        "deployment": "cloud"})
    speech.set_default_connection(connection["id"], connection["revision"], 0)
    store_before = speech.store.path.read_bytes()
    preset_path = tmp_path / "flow_presets.json"
    catalog = PresetCatalogService(user_presets_path=preset_path)
    starter = catalog.list_presets()[0]
    assert not preset_path.exists()
    assert [node["kind"] for node in starter["graph"]["nodes"]] == ["tts"]
    source = Path(__file__).resolve().parents[1] / "docs" / "examples" / "first-use.zh.srt"
    original = deepcopy(starter)
    profile, contexts = freeze_graph_connections({"version": 2, "graph": starter["graph"],
        "bindings": {"subtitle_1": {"path": str(source), "language": "zh", "language_confirmed": True}}}, settings={})
    assert contexts == {}
    prepared, values = prepare_graph_profile(profile)
    frozen = freeze_graph_speech(prepared)
    snapshot = frozen["_graph_runtime"]["node_snapshots"]["tts"]
    request = compile_recipe(snapshot["recipe"], build_plan("你好。"), {})[0]
    assert request["parameters"]["variant"]["value"] == "zh-CN-XiaoxiaoNeural"
    assert request["parameters"]["options"]["speed"] == 1
    assert snapshot["connection"]["id"] == "engine-default-edge"
    assert not snapshot["assets"]
    assert speech.store.path.read_bytes() == store_before
    models = MagicMock()
    models.list_models.side_effect = AssertionError("Starter must not query local model inventory")
    resources = ResourceService(project_root=tmp_path / "workspace", model_service=models)
    ready = resources.check_task_readiness(task_type="pipeline", execution_profile=frozen)
    assert ready["ready"], ready["issues"]
    assert ready["missing_requirements"] == []
    models.list_models.assert_not_called()
    assert subprocess.run([get_ffmpeg(), "-version"], capture_output=True, timeout=10).returncode == 0

    calls = []

    class MockEdge:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def synthesize(self, text, path):
            calls.append(text)
            # Deliberately synthetic data: validates wiring, not voice quality.
            sf.write(path, np.full(24000, .05), 24000)

    monkeypatch.setattr("src.core.tts.EdgeTTSEngine", MockEdge)
    output = tmp_path / "output"
    plan = build_graph_plan(frozen["graph"], frozen["bindings"], task_id="starter-check",
        output_dir=str(output), node_snapshots=frozen["_graph_runtime"]["node_snapshots"])
    results = GraphExecutor().execute(plan, slot_values=values,
        plan_for_node=lambda node: make_node_plan(node, task_id=plan.task_id,
            output_dir=str(output), snapshots=plan.node_snapshots))
    assert calls == [{"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%"}, values["subtitle_1"].segments[0]["text"]]
    assert results["node_states"] == {"tts": "completed"}
    assert [artifact["type"] for artifact in results["workflow_outputs"]] == ["audio.tts"]
    audio = sf.info(results["primary_output"])
    assert audio.duration == 8 and audio.frames > 0
    assert starter == original
    assert not preset_path.exists()


def test_demo_is_first_for_active_and_template_catalogs_independent_of_yaml_order(tmp_path):
    shipped = Path(__file__).resolve().parents[1] / "config/presets.yaml"
    definitions = yaml.safe_load(shipped.read_text(encoding="utf-8"))["presets"]
    path = tmp_path / "reordered.yaml"
    path.write_text(yaml.safe_dump({"presets": [*definitions[1:], definitions[0]]}), encoding="utf-8")
    user = tmp_path / "flow_presets.json"
    service = PresetCatalogService(path, user)
    expected = ["starter_edge_chinese_v1", "custom_07458dd97f9e467eb6aef34d499923a5",
                "custom_964998d159ec4c30a5cc6bf44b76caeb"]
    assert [item["id"] for item in service.list_presets()] == expected
    assert [item["id"] for item in service.list_builtin_templates()] == expected
    assert not user.exists()


def test_previous_builtin_descriptions_are_readable_without_rewriting_user_catalog(tmp_path):
    import json
    from src.app.services.preset_catalog_service import PresetConflictError
    import pytest

    shipped = Path(__file__).resolve().parents[1] / "config/presets.yaml"
    definitions = yaml.safe_load(shipped.read_text(encoding="utf-8"))["presets"]
    previous = ["无字幕输入， 正常流程", "输入希望语言字幕与原音频， 进行混音"]
    current = ["音频翻译配音并混音。", "字幕配音并与原音频混音。"]
    stored = []
    for index, (old, new) in enumerate(zip(previous, current, strict=True), 1):
        stored.append({**deepcopy(definitions[index]), "description": old, "builtin": False})
        definitions[index]["description"] = new
    path = tmp_path / "updated.yaml"
    path.write_text(yaml.safe_dump({"presets": definitions}), encoding="utf-8")
    user = tmp_path / "flow_presets.json"
    user.write_text(json.dumps({"version": 2, "presets": stored}, ensure_ascii=False), encoding="utf-8")
    original = user.read_bytes()
    items = PresetCatalogService(path, user).list_presets()
    assert [item["description"] for item in items[1:]] == current
    assert all(item["builtin"] for item in items)
    assert user.read_bytes() == original

    # A user's genuinely edited description is still a conflict, never discarded.
    stored[0]["description"] = "用户保留的说明"
    user.write_text(json.dumps({"version": 2, "presets": stored}, ensure_ascii=False), encoding="utf-8")
    edited = user.read_bytes()
    with pytest.raises(PresetConflictError):
        PresetCatalogService(path, user).list_presets()
    assert user.read_bytes() == edited
