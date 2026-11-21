from pathlib import Path
import hashlib
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import soundfile as sf

from src.api.http.schemas.workflow_graph import GraphDefinitionRequest
from src.app.services.graph_pipeline_service import make_node_plan
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.orchestration.pipeline.graph_adapters import GraphStageRunner, GraphValue
from src.core.orchestration.pipeline.graph_executor import GraphExecutor
from src.core.orchestration.pipeline.graph_validation import build_graph_plan
from src.core.speech.remake import prepare_references


def test_graph_remake_routes_both_stems_reference_and_detected_delivery(tmp_path, monkeypatch):
    source, subtitle = tmp_path / "source.wav", tmp_path / "target.srt"
    sf.write(source, np.zeros((16000, 2)), 16000)
    subtitle.write_text("unused in this typed graph test", encoding="utf-8")
    graph = {
        "version": 2,
        "nodes": [
            {"id": "sep", "kind": "separate", "provider": "demucs", "model": "mel_band_roformer"},
            {"id": "delivery", "kind": "delivery_detect", "provider": "local"},
            {"id": "dub", "kind": "tts", "provider": "speech", "target_lang": "zh",
             "options": {"borrow_silence_slack": True, "max_atempo": 1.3,
                         "acoustic_options": {"binaural_mode": "dynamic_hrtf"}}},
            {"id": "mix", "kind": "mix", "provider": "ffmpeg", "options": {"sidechain_ducking": True}},
        ],
        "input_slots": [{"id": "source", "type": "audio", "label": "录音"},
                        {"id": "target", "type": "subtitle", "label": "译文", "language": "zh"}],
        "edges": [],
        "outputs": [{"node_id": "mix", "port": "audio"}, {"node_id": "sep", "port": "background"}],
    }

    def edge(node_id, port, origin, output=None):
        graph["edges"].append({
            "target": {"node_id": node_id, "port": port},
            "source": ({"kind": "node", "node_id": origin, "port": output}
                       if output else {"kind": "slot", "slot_id": origin}),
        })

    edge("sep", "audio", "source")
    edge("delivery", "subtitle", "target")
    edge("delivery", "audio", "sep", "audio")
    edge("dub", "subtitle", "delivery", "subtitle")
    edge("dub", "reference_audio", "sep", "audio")
    edge("mix", "audio", "sep", "background")
    edge("mix", "speech", "dub", "audio")
    graph = GraphDefinitionRequest.model_validate(graph).model_dump()

    def separate(**kwargs):
        assert kwargs["model"] == "mel_band_roformer"
        assert kwargs["stems"] == ["vocals", "no_vocals"]
        outputs = {}
        for stem in kwargs["stems"]:
            path = Path(kwargs["output_dir"]) / f"{stem}.wav"
            sf.write(path, np.zeros((16000, 2)), 16000)
            outputs[stem] = str(path)
        return outputs

    def synthesize(snapshot, segments, path, task_id, **kwargs):
        assert segments[0]["delivery"] == "normal"
        assert segments[0]["auto_delivery"] is True
        assert Path(kwargs["binaural_source_path"]).name == "vocals.wav"
        assert kwargs["borrow_silence_slack"] is True
        assert kwargs["max_atempo"] == 1.3
        assert kwargs["acoustic_options"]["binaural_mode"] == "dynamic_hrtf"
        sf.write(path, np.zeros((16000, 2)), 16000)
        return {"experiment_id": "experiment", "id": "assembly"}

    def mix(**kwargs):
        assert Path(kwargs["original_path"]).name == "no_vocals.wav"
        assert kwargs["sidechain_ducking"] is True
        sf.write(kwargs["output_path"], np.zeros((16000, 2)), 16000)

    speech = SimpleNamespace(synthesize_timeline=synthesize)
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    monkeypatch.setattr(PipelineExecutor, "_try_clear_gpu", staticmethod(lambda: None))
    runtime = PipelineExecutor(separator=SimpleNamespace(separate=separate),
                               mixer_factory=lambda *_: SimpleNamespace(mix=mix))
    snapshots = {"dub": {"recipe": {"provider_id": "edge", "model": "edge-tts"}}}
    output = tmp_path / "out"
    plan = build_graph_plan(graph, {"source": {"path": str(source)}, "target": {"path": str(subtitle)}},
                            task_id="remake", output_dir=str(output), node_snapshots=snapshots)
    metadata = {"timeline_id": "same", "pair_confirmed": True, "duration": 1}
    result = GraphExecutor(GraphStageRunner(runtime)).execute(plan, slot_values={
        "source": GraphValue("audio", str(source), metadata=metadata),
        "target": GraphValue("subtitle", str(subtitle), [{"start": 0, "end": 1, "text": "你好"}],
                             {**metadata, "language": "zh"}),
    }, plan_for_node=lambda node: make_node_plan(node, task_id="remake", output_dir=str(output),
                                                snapshots=snapshots))
    assert [item["type"] for item in result["workflow_outputs"]] == ["audio.mix", "audio.background"]


def test_dynamic_reference_spans_keep_matching_source_transcripts(tmp_path):
    source = tmp_path / "source.wav"
    sf.write(source, .05 * np.sin(np.arange(16000 * 8) * .07), 16000)
    cues = [
        {"start_time": 0, "end_time": 2, "original": "ひとつ", "delivery": "whisper"},
        {"start_time": 2.1, "end_time": 4.5, "original": "ふたつ", "delivery": "whisper"},
        {"start_time": 5, "end_time": 8, "original": "おわり", "delivery": "normal"},
    ]
    assets, refs = prepare_references(source, cues, "per_style", tmp_path / "refs")
    assert refs[0] == refs[1] != refs[2]
    assert assets[refs[0]]["transcript"] == "ひとつ ふたつ"
    assert sf.info(assets[refs[0]]["path"]).duration == 4.5
    assert assets[refs[2]]["transcript"] == "おわり"


def test_seed_vc_uses_aligned_reference_and_preserves_raw_takes(tmp_path, monkeypatch):
    from packages.protocol.compute import VcBatchItemResult, VcBatchResult
    from src.app.services import speech_service

    raw = tmp_path / "raw.wav"
    sf.write(raw, np.zeros(8000), 16000)
    original = raw.read_bytes()
    provider = SimpleNamespace(_has_remote_worker=lambda _: True,
                               _resolve_remote_worker_config=lambda _: ("http://worker.invalid", None, 1, None))
    monkeypatch.setattr(speech_service, "get_provider", lambda _: provider)
    service = speech_service.SpeechService(store=Mock(), tasks=Mock(), dispatcher=Mock(), artifacts=Mock())
    monkeypatch.setattr(service, "connection_context", lambda _: {})
    received = []

    def convert(client, request):
        received.append(request)
        for item in request.items:
            shutil.copyfile(item.source_audio_path, item.output_path)
        return VcBatchResult(items=[VcBatchItemResult(id=item.id, output_path=item.output_path)
                                    for item in request.items])

    monkeypatch.setattr("packages.gpu_worker.client.ComputeClient.vc_batch", convert)
    experiment = {
        "snapshot": {"recipe": {"provider_id": "edge", "variant": {"kind": "builtin"}},
                     "connection": {}, "assets": {}},
        "vc_refinement": {"enabled": True, "diffusion_steps": 25},
        "remake_references": {"ref": {"path": str(raw), "sha256": hashlib.sha256(original).hexdigest()}},
        "cue_references": {"sentence-1": "ref"},
    }
    takes = [({"id": f"sentence-{i}"}, {"id": str(i), "audio_path": str(raw)}) for i in (1, 2)]
    converted = service._refine_takes(experiment, takes, tmp_path, lambda: False)

    assert [item.reference_id for item in received[0].items] == ["ref", "ref"]
    assert raw.read_bytes() == original
    assert all(Path(take["audio_path"]).parent == tmp_path / "refined" for _, take in converted)
