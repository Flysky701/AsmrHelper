"""Explicit, side-effect-free migration. Historical tasks remain on their V1 path."""
from __future__ import annotations

from copy import deepcopy

from .graph_catalog import GRAPH_CATALOG, GRAPH_NODE_KINDS
from .graph_models import GraphValidationError
from .graph_validation import validate_graph


_DEFAULTS = {
    "separate": ("demucs", "htdemucs"), "asr": ("faster_whisper", "faster-whisper-base"),
    "align": ("qwen3_forced_aligner", "qwen3-forced-aligner-0.6b"),
    "translate": ("deepseek", None), "tts": ("speech", None),
    "mix": ("ffmpeg", None), "export": ("ffmpeg", None),
}
_ALIASES = {"separation": "separate", "translation": "translate"}
_MATERIAL_FIELDS = {"path", "language", "language_confirmed", "audio_path", "pair_confirmed", "sha256"}


def _fail(message):
    raise GraphValidationError([{"code": "legacy_migration", "message": message}])


def _node(kind, stage, source_lang, target_lang):
    provider, model = _DEFAULTS[kind]
    options = deepcopy(stage.get("options", {}))
    provider_options = deepcopy(stage.get("provider_options", {}))
    if not isinstance(options, dict) or not isinstance(provider_options, dict):
        _fail("旧节点参数格式无效")
    if "speech_snapshot" in provider_options:
        _fail("历史任务快照不能作为可编辑模板，请重新选择已有配方")
    source = options.pop("source_lang", source_lang)
    target = options.pop("target_lang", target_lang)
    language = options.pop("language", None)
    if kind in {"asr", "align"} and language:
        source = language
    if kind == "tts" and language:
        target = language
    # Explicit workflow validation already superseded these historical mode flags.
    if kind == "translate":
        for name in ("direct_tts", "reuse_only", "reuse_unverified", "reuse_companion_paths",
                     "direct_subtitle_path", "direct_subtitle_sha256", "reuse_existing"):
            options.pop(name, None)
    return {"id": kind, "kind": kind, "provider": stage.get("provider") or provider,
            "model": stage.get("model", model),
            "source_lang": source if kind in {"asr", "align", "translate"} else None,
            "target_lang": target if kind in {"translate", "tts"} else None,
            "options": options, "provider_options": provider_options}


def legacy_profile_to_graph(profile: dict) -> dict:
    """Convert only explicit V1 bindings; return graph + runtime bindings, never defaults-as-edges."""
    if not isinstance(profile, dict) or profile.get("version") != 1:
        _fail("只能迁移 version 1 执行配置")
    workflow, stages = profile.get("workflow"), profile.get("stages")
    if not isinstance(workflow, dict) or workflow.get("version") != 1 or not isinstance(stages, dict):
        _fail("旧配置没有明确素材绑定，请保留旧流程或重新选择节点输入")
    if set(stages) - set(GRAPH_NODE_KINDS):
        _fail("旧配置包含未知阶段")
    if any(not isinstance(stage, dict) or type(stage.get("enabled")) is not bool for stage in stages.values()):
        _fail("旧配置必须明确各阶段是否启用")
    selected = [kind for kind in GRAPH_NODE_KINDS if stages.get(kind, {}).get("enabled") is True]
    graph = {"version": 2, "nodes": [_node(kind, stages[kind], profile.get("source_lang", "ja"),
                                         profile.get("target_lang", "zh")) for kind in selected],
             "edges": [], "input_slots": [], "outputs": []}
    bindings = {}
    prior = workflow.get("bindings", {})
    if not isinstance(prior, dict):
        _fail("旧素材绑定格式无效")
    for kind in selected:
        for port, material_type in GRAPH_CATALOG[kind]["inputs"].items():
            role = "text" if port == "subtitle" else port
            stage_bindings = prior.get(kind, {})
            reference = stage_bindings.get(role) if isinstance(stage_bindings, dict) else None
            if not isinstance(reference, dict):
                _fail(f"{kind}.{role} 缺少明确来源，不能自动补连线")
            if reference.get("kind") == "stage":
                previous = reference.get("stage")
                if previous not in selected:
                    _fail(f"{kind}.{role} 引用了未选择阶段")
                output_port = next(iter(GRAPH_CATALOG[previous]["outputs"]))
                source = {"kind": "node", "node_id": previous, "port": output_port}
            elif reference.get("kind") == "asset":
                slot_id = f"{kind}_{port}"
                slot = {"id": slot_id, "type": material_type, "label": f"{GRAPH_CATALOG[kind]['label']} {role}"}
                if reference.get("language_confirmed") is True and reference.get("language"):
                    slot["language"] = reference["language"]
                graph["input_slots"].append(slot)
                bindings[slot_id] = {key: deepcopy(value) for key, value in reference.items() if key in _MATERIAL_FIELDS}
                source = {"kind": "slot", "slot_id": slot_id}
            else:
                _fail(f"{kind}.{role} 素材来源格式无效")
            graph["edges"].append({"source": source, "target": {"node_id": kind, "port": port}})
    outputs = workflow.get("outputs")
    if not isinstance(outputs, list):
        _fail("旧配置缺少明确产出")
    for kind in outputs:
        if kind not in selected:
            _fail("旧配置的产出阶段未选择")
        graph["outputs"].append({"node_id": kind, "port": next(iter(GRAPH_CATALOG[kind]["outputs"]))})
    return {"graph": validate_graph(graph), "bindings": bindings}


def legacy_preset_to_graph(preset: dict, *, source_lang: str = "ja", target_lang: str = "zh") -> dict:
    """Old stage-only templates have no edges to infer: expose each required input as a slot."""
    if not isinstance(preset, dict):
        _fail("旧预设格式无效")
    stages, outputs = preset.get("stages"), preset.get("outputs", preset.get("stages"))
    if not isinstance(stages, list) or not isinstance(outputs, list):
        _fail("旧预设必须明确 stages 和 outputs")
    if any(not isinstance(value, str) for value in [*stages, *outputs]):
        _fail("旧预设阶段名称无效")
    selected = [_ALIASES.get(kind, kind) for kind in stages]
    outputs = [_ALIASES.get(kind, kind) for kind in outputs]
    if len(set(selected)) != len(selected) or any(kind not in GRAPH_CATALOG for kind in selected):
        _fail("旧预设包含重复或未知阶段")
    if any(kind not in selected for kind in outputs):
        _fail("旧预设产出对应阶段未选择")
    graph = {"version": 2, "nodes": [_node(kind, {}, source_lang, target_lang) for kind in selected],
             "edges": [], "input_slots": [], "outputs": []}
    for node in graph["nodes"]:
        for port, material_type in GRAPH_CATALOG[node["kind"]]["inputs"].items():
            slot_id = f"{node['id']}_{port}"
            slot = {"id": slot_id, "type": material_type, "label": f"{GRAPH_CATALOG[node['kind']]['label']} {port}"}
            if material_type == "subtitle" and node["kind"] in {"align", "translate", "tts"}:
                slot["language"] = target_lang if node["kind"] == "tts" else source_lang
            graph["input_slots"].append(slot)
            graph["edges"].append({"source": {"kind": "slot", "slot_id": slot_id},
                                   "target": {"node_id": node["id"], "port": port}})
    graph["outputs"] = [{"node_id": kind, "port": next(iter(GRAPH_CATALOG[kind]["outputs"]))} for kind in outputs]
    return validate_graph(graph, template=True)
