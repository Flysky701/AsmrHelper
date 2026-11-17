"""Graph contracts for local audio nodes, without models or user audio/state."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pydantic import ValidationError
import pytest
import soundfile as sf

from src.api.http.schemas.workflow_graph import GraphDefinitionRequest
from src.app.services.graph_pipeline_service import make_node_plan, prepare_graph_profile
from src.app.services.preset_catalog_service import PresetCatalogService
from src.core.orchestration.pipeline.graph_adapters import GraphStageRunner, GraphValue
from src.core.orchestration.pipeline.graph_catalog import input_ports
from src.core.orchestration.pipeline.graph_executor import GraphExecutor
from src.core.orchestration.pipeline.graph_legacy import legacy_preset_to_graph
from src.core.orchestration.pipeline.graph_models import GraphValidationError
from src.core.orchestration.pipeline.graph_validation import build_graph_plan, validate_graph


def _mix_graph():
    tracks = [
        {"id": "bed", "gain": .5, "offset_ms": 0, "muted": False},
        {"id": "effect", "gain": .25, "offset_ms": 100, "muted": False},
        {"id": "spare", "gain": 1, "offset_ms": -50, "muted": True},
    ]
    return {
        "version": 2,
        "nodes": [{"id": "mix", "kind": "mix", "provider": "ffmpeg",
                   "options": {"tracks": tracks}}],
        "input_slots": [{"id": t["id"], "type": "audio", "label": t["id"]} for t in tracks],
        "edges": [{"source": {"kind": "slot", "slot_id": t["id"]},
                   "target": {"node_id": "mix", "port": t["id"]}} for t in tracks],
        "outputs": [{"node_id": "mix", "port": "audio"}],
    }


def _difference_mix_graph():
    graph = _mix_graph()
    graph["nodes"].insert(0, {"id": "difference", "kind": "audio_difference", "provider": "local",
                             "options": {"alignment": "manual", "offset_ms": 0,
                                         "gain_left": 1, "gain_right": 1, "match_gain": False}})
    graph["input_slots"] += [{"id": p, "type": "audio", "label": p} for p in ("reference", "mixed")]
    graph["edges"][0]["source"] = {"kind": "node", "node_id": "difference", "port": "audio"}
    graph["edges"] += [{"source": {"kind": "slot", "slot_id": p},
                        "target": {"node_id": "difference", "port": p}} for p in ("reference", "mixed")]
    graph["outputs"].append({"node_id": "difference", "port": "audio"})
    return graph


def _write_audio(tmp_path, name, values, rate=8000):
    path = tmp_path / name
    sf.write(path, values, rate, subtype="FLOAT")
    return str(path)


def test_strict_request_round_trip_preserves_dynamic_ports_and_options():
    graph = _difference_mix_graph()
    normalized = GraphDefinitionRequest.model_validate(graph).model_dump()
    assert input_ports(normalized["nodes"][1]) == {"bed": "audio", "effect": "audio", "spare": "audio"}
    assert validate_graph(json.loads(json.dumps(normalized))) == validate_graph(graph)
    assert normalized["nodes"][1]["options"] == graph["nodes"][1]["options"]
    invalid = deepcopy(graph)
    invalid["nodes"][1]["options"]["tracks"][0]["gain"] = "0.5"
    with pytest.raises(ValidationError):
        GraphDefinitionRequest.model_validate(invalid)


@pytest.mark.parametrize("tracks", [
    [], [{"id": "bad port"}], [{"id": "bed"}, {"id": "BED"}],
    [{"id": "bed", "gain": -1}], [{"id": "bed", "offset_ms": True}],
    [{"id": "bed", "muted": "false"}], [{"id": "bed", "path": "private.wav"}],
])
def test_invalid_track_definitions_are_rejected_before_port_resolution(tracks):
    graph = _mix_graph()
    graph["nodes"][0]["options"]["tracks"] = tracks
    with pytest.raises(GraphValidationError):
        validate_graph(graph)


@pytest.mark.parametrize("mutation,code", [("missing", "missing_input"), ("duplicate", "multiple_sources"),
                                          ("unknown", "unknown_port"), ("subtitle", "type_mismatch")])
def test_dynamic_track_connections_are_validated(mutation, code):
    graph = _mix_graph()
    if mutation == "missing":
        graph["edges"].pop()
    elif mutation == "duplicate":
        graph["edges"].append(deepcopy(graph["edges"][0]))
    elif mutation == "unknown":
        graph["edges"][0]["target"]["port"] = "removed_track"
    else:
        graph["input_slots"][0]["type"] = "subtitle"
    with pytest.raises(GraphValidationError) as caught:
        validate_graph(graph)
    assert code in {issue["code"] for issue in caught.value.issues}


def test_preset_save_reload_retains_graph_connections_and_legacy_defaults(tmp_path):
    builtins = Path(__file__).resolve().parents[1] / "config" / "presets.yaml"
    path = tmp_path / "presets.json"
    service = PresetCatalogService(builtins, path)
    graph = _difference_mix_graph()
    saved = service.create_preset({"version": 2, "label": "Difference and mix", "graph": graph})
    legacy = legacy_preset_to_graph({"stages": ["mix"], "outputs": ["mix"]})
    old = service.create_preset({"version": 2, "label": "Old two-track", "graph": legacy})
    reloaded = {item["id"]: item for item in PresetCatalogService(builtins, path).list_presets()}
    assert reloaded[saved["id"]] == saved
    assert reloaded[old["id"]] == old
    assert GraphDefinitionRequest.model_validate(reloaded[saved["id"]]["graph"])
    legacy_node = reloaded[old["id"]]["graph"]["nodes"][0]
    assert input_ports(legacy_node) == {"audio": "audio", "speech": "audio"}
    assert "tracks" not in legacy_node["options"]
    plan = make_node_plan(legacy_node, task_id="legacy", output_dir=str(tmp_path), snapshots={})
    assert plan.mix.output_length == "main"
    assert plan.mix.original_volume == .85
    assert plan.mix.tts_volume_ratio == .5


def test_independent_mix_sources_prepare_but_legacy_pairing_remains_required(tmp_path):
    paths = [_write_audio(tmp_path, f"source-{i}.wav", np.full(800, .02 * (i + 1))) for i in range(3)]
    graph = _mix_graph()
    profile = {"version": 2, "graph": graph,
               "bindings": {slot["id"]: {"path": path} for slot, path in zip(graph["input_slots"], paths, strict=True)}}
    prepared, values = prepare_graph_profile(profile, declared_paths=paths)
    assert len({value.metadata["timeline_id"] for value in values.values()}) == 3
    assert prepared["_graph_runtime"]["asset_identities"]
    assert make_node_plan(prepared["graph"]["nodes"][0], task_id="new", output_dir=str(tmp_path), snapshots={}) is None
    legacy = legacy_preset_to_graph({"stages": ["mix"], "outputs": ["mix"]})
    bindings = {slot["id"]: {"path": path} for slot, path in zip(legacy["input_slots"], paths, strict=False)}
    with pytest.raises(ValueError):
        prepare_graph_profile({"version": 2, "graph": legacy, "bindings": bindings})


def test_legacy_mix_adapter_still_calls_existing_executor_and_checks_pairing(tmp_path):
    node = legacy_preset_to_graph({"stages": ["mix"], "outputs": ["mix"]})["nodes"][0]
    plan = make_node_plan(node, task_id="legacy", output_dir=str(tmp_path), snapshots={})
    paths = [_write_audio(tmp_path, f"legacy-{i}.wav", np.zeros(800)) for i in range(2)]
    inputs = {port: GraphValue("audio", path, metadata={"duration": .1, "timeline_id": "same",
                                                       "pair_confirmed": True})
              for port, path in zip(("audio", "speech"), paths, strict=True)}
    calls = []

    def execute_stage(kind, actual_plan, **kwargs):
        calls.append((kind, actual_plan, kwargs))
        return {"path": paths[0]}

    runner = GraphStageRunner(SimpleNamespace(execute_stage=execute_stage),
                              audio_inspector=lambda _: {"duration": .1})
    result = runner.run(node, inputs, plan, tmp_path / "old")
    assert len(calls) == 1 and calls[0][0] == "mix" and calls[0][1] is plan
    assert calls[0][2]["audio_path"] == paths[0] and calls[0][2]["speech_path"] == paths[1]
    assert result["audio"].metadata["output_length"] == "main"
    inputs["speech"] = GraphValue("audio", paths[1], metadata={"duration": .1, "timeline_id": "different",
                                                               "pair_confirmed": True})
    with pytest.raises(ValueError):
        runner.run(node, inputs, plan, tmp_path / "invalid")
    assert len(calls) == 1


def test_real_difference_to_multitrack_dag_registers_playable_audio_and_metadata(tmp_path):
    from src.app.services.artifact_service import ArtifactService
    from src.app.services.pipeline_service import PipelineService

    rate = 8000
    time = np.arange(2400) / rate
    reference = .1 * np.sin(2 * np.pi * 220 * time)
    addition = .03 * np.sin(2 * np.pi * 410 * time)
    effect = .02 * np.sin(2 * np.pi * 630 * time)
    paths = {name: _write_audio(tmp_path, f"{name}.wav", audio) for name, audio in
             (("reference", reference), ("mixed", reference + addition), ("effect", effect), ("spare", effect))}
    profile, slots = prepare_graph_profile({"version": 2, "graph": _difference_mix_graph(),
                                            "bindings": {key: {"path": value} for key, value in paths.items()}})
    root = str(tmp_path / "outputs")
    plan = build_graph_plan(profile["graph"], profile["bindings"], task_id="audio-test", output_dir=root)
    results = GraphExecutor().execute(plan, slot_values=slots, plan_for_node=lambda node:
                                     make_node_plan(node, task_id="audio-test", output_dir=root, snapshots={}))
    assert results["node_states"] == {"difference": "completed", "mix": "completed"}
    outputs = {item["node_id"]: item for item in results["workflow_outputs"]}
    difference = outputs["difference"]
    mix = outputs["mix"]
    actual, actual_rate = sf.read(difference["path"])
    assert actual_rate == rate and np.max(np.abs(actual - addition)) < 1e-6
    actual_mix, actual_rate = sf.read(mix["path"])
    expected = np.zeros(3200)
    expected[:2400] += addition * .5
    expected[800:] += effect * .25
    assert actual_rate == rate and np.max(np.abs(actual_mix - expected)) < 1e-6
    assert difference["type"] == "audio.difference" and difference["preview"] == "audio"
    assert difference["metadata"]["warnings"] and difference["metadata"]["gains"] == [1]
    assert difference["metadata"]["coverage_end"] == pytest.approx(.3)
    assert mix["metadata"]["output_length"] == "longest" and mix["metadata"]["track_count"] == 3
    assert mix["metadata"]["timeline_id"] != difference["metadata"]["timeline_id"]
    assert mix["metadata"]["tracks"] == profile["graph"]["nodes"][1]["options"]["tracks"]
    artifacts = ArtifactService()
    PipelineService._register_pipeline_artifacts(SimpleNamespace(_artifact_service=artifacts),
        task_id="audio-test", results=results, mix_path=None, exported_subtitle=None)
    preview = artifacts.get_task_preview_view("audio-test")
    assert preview["artifact_count"] == 2 and preview["preview_modes"] == ["audio"]
    assert {entry.artifact_type for entry in preview["artifacts"]} == {"audio.mix", "audio.difference"}
    assert all(Path(entry.path).is_file() and entry.metadata["node_id"] in outputs for entry in preview["artifacts"])


@pytest.mark.parametrize("bad_value", [None, GraphValue("subtitle", "absent"),
                                       GraphValue("audio", "absent", metadata={"duration": 1})])
def test_new_audio_adapter_rejects_missing_wrong_type_or_absent_files(tmp_path, bad_value):
    from src.core.orchestration.pipeline.graph_audio import run_audio_node

    graph = _mix_graph()
    inputs = {"bed": bad_value}
    with pytest.raises(ValueError):
        run_audio_node(graph["nodes"][0], inputs, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
