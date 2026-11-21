from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import soundfile as sf
import yaml

from src.app.services.preset_catalog_service import PresetCatalogService


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
