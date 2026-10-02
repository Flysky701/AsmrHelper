"""Pure graph validation: no filesystem, provider probing, inference or implicit edges."""
from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from .graph_catalog import GRAPH_CATALOG, GRAPH_LANGUAGES, GRAPH_OPTION_KEYS, GRAPH_PORT_TYPES
from .graph_models import GraphExecutionPlan, GraphValidationError


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_FORBIDDEN = {
    "api_key", "apikey", "credential", "credentials", "token", "password", "authorization",
    "headers", "secret", "secrets", "access_token", "refresh_token", "credential_ref",
    "speech_snapshot", "snapshot", "node_snapshots", "runtime", "bindings", "asset_identity",
    "path", "audio_path", "reference_path", "reference_audio", "model_path", "output_dir",
}
_NODE_FIELDS = {"id", "kind", "provider", "model", "source_lang", "target_lang", "options", "provider_options"}
_BINDING_FIELDS = {"path", "language", "language_confirmed", "audio_path", "pair_confirmed",
                   "sha256", "asset_id", "resolved_language", "asset_identity"}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _portable(value: Any, location: str, add, *, depth: int = 0) -> None:
    if depth > 16:
        add("invalid_options", f"{location} 嵌套过深")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                add("invalid_options", f"{location} 参数名称必须是字符串")
                continue
            normalized = key.lower().replace("-", "_")
            if normalized in _FORBIDDEN or normalized.endswith("_path"):
                add("nonportable_parameter", f"{location}.{key} 不能保存在图定义；请选择连接或素材槽")
            else:
                _portable(item, f"{location}.{key}", add, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _portable(item, location, add, depth=depth + 1)
    elif isinstance(value, str):
        if (re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\", "file:", "data:"))
                or re.match(r"^https?://[^/]*@", value, re.IGNORECASE)):
            add("nonportable_parameter", f"{location} 不能包含本机路径、内嵌素材或凭据")
    elif value is not None and (not isinstance(value, (bool, int, float))
                                or isinstance(value, float) and not math.isfinite(value)):
        add("invalid_options", f"{location} 必须是有限的 JSON 参数")


def topological_node_ids(graph: dict) -> list[str]:
    """Stable Kahn order; callers validate endpoint shapes before calling this helper."""
    ids = [node["id"] for node in graph["nodes"]]
    dependencies = {node_id: set() for node_id in ids}
    for edge in graph["edges"]:
        if edge["source"]["kind"] == "node":
            dependencies[edge["target"]["node_id"]].add(edge["source"]["node_id"])
    result: list[str] = []
    done: set[str] = set()
    while len(result) < len(ids):
        ready = next((node_id for node_id in ids if node_id not in done and dependencies[node_id] <= done), None)
        if ready is None:
            raise GraphValidationError([{"code": "cycle", "message": "节点连线存在循环，请移除循环后再运行"}])
        result.append(ready)
        done.add(ready)
    return result


def validate_graph(graph: Any, *, template: bool = False) -> dict[str, Any]:
    """Validate the single graph authority and return a detached normalized value.

    Template and run definitions share the same portable contract. Missing *material*
    bindings are allowed here; missing ports are not. No upstream step is inserted.
    """
    issues: list[dict[str, str]] = []

    def add(code, message, node_id=None, port=None):
        issues.append({"code": code, "message": message,
                       **({"node_id": node_id} if isinstance(node_id, str) else {}),
                       **({"port": port} if isinstance(port, str) else {})})

    if not isinstance(graph, dict) or graph.keys() - {"version", "nodes", "edges", "input_slots", "outputs"}:
        raise GraphValidationError([{"code": "invalid_graph", "message": "图定义包含未知字段或格式无效"}])
    if type(graph.get("version")) is not int or graph["version"] != 2:
        add("invalid_version", "图定义必须使用 version 2")
    bounds = {"nodes": (1, 64), "edges": (0, 256), "input_slots": (0, 64), "outputs": (1, 128)}
    for field, (minimum, maximum) in bounds.items():
        value = graph.get(field)
        if not isinstance(value, list) or not minimum <= len(value) <= maximum:
            add("invalid_graph", f"{field} 必须包含 {minimum} 至 {maximum} 项")
    if issues:
        raise GraphValidationError(issues)
    result = deepcopy(graph)
    nodes, slots = {}, {}
    for node in result["nodes"]:
        if not isinstance(node, dict) or node.keys() - _NODE_FIELDS:
            add("invalid_node", "节点包含未知字段或格式无效")
            continue
        node_id = node.get("id")
        if not _identifier(node_id) or node_id.casefold() in {item.casefold() for item in nodes}:
            add("duplicate_or_invalid_id", "节点编号无效或重复", node_id)
            continue
        nodes[node_id] = node
        kind = node.get("kind")
        if not isinstance(kind, str) or kind not in GRAPH_CATALOG:
            add("unknown_kind", "未知节点能力", node_id)
        provider = node.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            add("missing_provider", "请选择节点使用的引擎", node_id)
        _portable(provider, "provider", lambda c, m: add(c, m, node_id))
        model = node.setdefault("model", None)
        if model is not None and not isinstance(model, str):
            add("invalid_model", "模型必须是名称或空值", node_id)
        for name in ("source_lang", "target_lang"):
            language = node.setdefault(name, None)
            if language is not None and language not in GRAPH_LANGUAGES:
                add("invalid_language", "语言仅支持 ja、zh、en", node_id)
        for required in (("source_lang", "target_lang") if kind == "translate" else
                         ("source_lang",) if kind in ("asr", "align") else
                         ("target_lang",) if kind == "tts" else ()):
            if node.get(required) not in GRAPH_LANGUAGES:
                add("missing_language", f"请选择该节点的 {required}", node_id)
        for field in ("options", "provider_options"):
            options = node.setdefault(field, {})
            if not isinstance(options, dict):
                add("invalid_options", f"{field} 必须是参数对象", node_id)
                continue
            if any(key in options for key in ("source_lang", "target_lang", "language")):
                add("duplicate_language", "语言只能由节点 source_lang/target_lang 指定", node_id)
            _portable(options, field, lambda c, m: add(c, m, node_id))
        _portable(model, "model", lambda c, m: add(c, m, node_id))
        if isinstance(kind, str) and kind in GRAPH_CATALOG:
            allowed = GRAPH_OPTION_KEYS[kind]
            options, provider_options = node.get("options"), node.get("provider_options")
            if allowed is not None and isinstance(options, dict) and options.keys() - set(allowed):
                add("unsupported_option", "节点包含当前能力不会执行的参数", node_id)
            if kind not in {"asr", "translate"} and provider_options:
                add("unsupported_option", "该节点不接收顶层 provider_options；配音参数请放在 speech_source 中", node_id)
            fixed_provider = {"separate": "demucs", "align": "qwen3_forced_aligner", "mix": "ffmpeg", "export": "ffmpeg"}.get(kind)
            if fixed_provider and provider != fixed_provider:
                add("unsupported_provider", f"该能力当前仅接线 {fixed_provider}", node_id)
            if kind == "align" and model not in (None, "default", "qwen3-forced-aligner-0.6b"):
                add("unsupported_model", "时间轴校准当前仅接线 qwen3-forced-aligner-0.6b", node_id)
            if kind in {"mix", "export"} and model not in (None, "default"):
                add("unsupported_model", "该节点不使用模型，请清空模型字段", node_id)
            if kind == "separate" and isinstance(options, dict) and options.get("mode", "vocals") != "vocals":
                add("unsupported_option", "分离节点当前仅提供人声轨输出", node_id)
            if kind == "mix" and isinstance(options, dict):
                if options.get("output_length", "main") not in ("main", "longest"):
                    add("invalid_option", "output_length 必须是 main 或 longest", node_id)
                for key, value in options.items():
                    if key in ("original_volume", "tts_volume_ratio", "tts_delay_ms") and (
                            type(value) not in (float, int) or not math.isfinite(value)
                            or key != "tts_delay_ms" and value < 0):
                        add("invalid_option", f"{key} 必须是有效数值，音量不能为负数", node_id)
        if kind == "export" and isinstance(node.get("options"), dict) and node["options"].get("subtitle_format", "srt") not in ("srt", "vtt", "lrc"):
            add("invalid_format", "字幕导出仅支持 SRT、VTT、LRC", node_id)
    for slot in result["input_slots"]:
        if not isinstance(slot, dict) or slot.keys() - {"id", "type", "label", "language"}:
            add("invalid_slot", "素材槽包含未知字段或格式无效")
            continue
        slot_id = slot.get("id")
        if not _identifier(slot_id) or slot_id.casefold() in {item.casefold() for item in slots}:
            add("duplicate_or_invalid_slot", "素材槽编号无效或重复")
            continue
        slots[slot_id] = slot
        if slot.get("type") not in GRAPH_PORT_TYPES:
            add("invalid_slot_type", "素材槽类型必须是 audio 或 subtitle")
        if not isinstance(slot.get("label"), str) or not slot["label"].strip() or len(slot["label"]) > 100:
            add("invalid_slot_label", "素材槽需要不超过 100 字符的名称")
        if slot.get("language") is None:
            slot.pop("language", None)
        if "language" in slot and slot["language"] not in GRAPH_LANGUAGES:
            add("invalid_language", "素材槽声明语言无效")
    if issues:
        raise GraphValidationError(issues)
    connected: set[tuple[str, str]] = set()
    for edge in result["edges"]:
        if not isinstance(edge, dict) or set(edge) != {"source", "target"}:
            add("invalid_edge", "连线必须有 source 和 target")
            continue
        source, target = edge["source"], edge["target"]
        if not isinstance(target, dict) or set(target) != {"node_id", "port"}:
            add("invalid_target", "目标端口格式无效")
            continue
        node_id, port = target["node_id"], target["port"]
        if not isinstance(node_id, str) or node_id not in nodes or not isinstance(port, str):
            add("unknown_target", "连线目标节点不存在", node_id)
            continue
        required_type = GRAPH_CATALOG[nodes[node_id]["kind"]]["inputs"].get(port)
        if required_type is None:
            add("unknown_port", "节点没有该输入端口", node_id, port)
            continue
        if (node_id, port) in connected:
            add("multiple_sources", "每个输入端口只能绑定一个来源", node_id, port)
        connected.add((node_id, port))
        provided_type = None
        if isinstance(source, dict) and source.get("kind") == "slot" and set(source) == {"kind", "slot_id"}:
            slot_id = source["slot_id"]
            if isinstance(slot_id, str) and slot_id in slots:
                provided_type = slots[slot_id]["type"]
        elif isinstance(source, dict) and source.get("kind") == "node" and set(source) == {"kind", "node_id", "port"}:
            origin, output_port = source["node_id"], source["port"]
            if isinstance(origin, str) and origin in nodes and isinstance(output_port, str):
                provided_type = GRAPH_CATALOG[nodes[origin]["kind"]]["outputs"].get(output_port)
        if provided_type is None:
            add("unknown_source", "连线来源节点、素材槽或端口不存在", node_id, port)
        elif provided_type != required_type:
            add("type_mismatch", f"该端口需要 {required_type}，来源为 {provided_type}", node_id, port)
    for node_id, node in nodes.items():
        for port in GRAPH_CATALOG[node["kind"]]["inputs"]:
            if (node_id, port) not in connected:
                add("missing_input", "请选择素材槽或明确的上游产物", node_id, port)
    seen_outputs = set()
    for output in result["outputs"]:
        if not isinstance(output, dict) or output.keys() - {"node_id", "port", "label"}:
            add("invalid_output", "交付产出格式无效")
            continue
        node_id, port = output.get("node_id"), output.get("port")
        if not isinstance(node_id, str) or node_id not in nodes or not isinstance(port, str):
            add("unknown_output", "交付产出引用的节点不存在", node_id)
            continue
        if port not in GRAPH_CATALOG[nodes[node_id]["kind"]]["outputs"]:
            add("unknown_output_port", "交付产出引用的端口不存在", node_id, port)
        if (node_id, port) in seen_outputs:
            add("duplicate_output", "交付产出重复", node_id, port)
        seen_outputs.add((node_id, port))
        if output.get("label") is None:
            output.pop("label", None)
        if "label" in output and (not isinstance(output["label"], str) or len(output["label"]) > 100):
            add("invalid_output_label", "产出名称必须是最多 100 字符的文本", node_id, port)
    if issues:
        raise GraphValidationError(issues)
    order = topological_node_ids(result)
    # Known languages propagate through the graph without probing actual materials.
    languages: dict[str, str | None] = {}
    for node_id in order:
        node = nodes[node_id]
        incoming = next((edge["source"] for edge in result["edges"]
                         if edge["target"] == {"node_id": node_id, "port": "subtitle"}), None)
        language = (slots[incoming["slot_id"]].get("language") if incoming and incoming["kind"] == "slot"
                    else languages.get(incoming["node_id"]) if incoming else None)
        expected = node["target_lang"] if node["kind"] == "tts" else node["source_lang"]
        if node["kind"] in {"align", "translate", "tts"} and language and language != expected:
            add("language_mismatch", f"输入字幕语言 {language} 与节点所需语言 {expected} 不同", node_id, "subtitle")
        languages[node_id] = (node["source_lang"] if node["kind"] == "asr" else
                              node["target_lang"] if node["kind"] == "translate" else language)
    if issues:
        raise GraphValidationError(issues)
    return result


def build_graph_plan(graph: Any, bindings: Any = None, *, task_id: str = "", output_dir: str = "",
                     node_snapshots: dict[str, dict[str, Any]] | None = None) -> GraphExecutionPlan:
    normalized = validate_graph(graph)
    bindings = {} if bindings is None else deepcopy(bindings)
    if not isinstance(bindings, dict):
        raise GraphValidationError([{"code": "invalid_bindings", "message": "素材绑定必须是对象"}])
    slot_ids = {slot["id"] for slot in normalized["input_slots"]}
    used = {edge["source"]["slot_id"] for edge in normalized["edges"] if edge["source"]["kind"] == "slot"}
    issues = []
    for slot_id in bindings:
        if slot_id not in slot_ids:
            issues.append({"code": "unknown_binding", "message": "素材绑定引用了未知素材槽"})
    for slot_id in used:
        value = bindings.get(slot_id)
        if isinstance(value, dict):
            # Public schemas represent absent optional fields as None when dumped.
            for field in ("language", "audio_path", "sha256", "resolved_language", "asset_identity", "asset_id"):
                if value.get(field) is None:
                    value.pop(field, None)
        valid = isinstance(value, dict) and not value.keys() - _BINDING_FIELDS
        valid = valid and isinstance(value.get("path"), str) and bool(value["path"].strip())
        if not valid:
            issues.append({"code": "missing_material", "slot_id": slot_id, "message": "请为素材槽选择明确的文件"})
            continue
        for flag in ("language_confirmed", "pair_confirmed"):
            if flag in value and type(value[flag]) is not bool:
                issues.append({"code": "invalid_binding", "slot_id": slot_id, "message": f"{flag} 必须是布尔值"})
        for field in ("language", "resolved_language"):
            if field in value and value[field] not in GRAPH_LANGUAGES:
                issues.append({"code": "invalid_binding", "slot_id": slot_id, "message": "素材语言无效"})
        if "audio_path" in value and (not isinstance(value["audio_path"], str) or not value["audio_path"].strip()):
            issues.append({"code": "invalid_binding", "slot_id": slot_id, "message": "对应音频路径无效"})
        if "sha256" in value and (not isinstance(value["sha256"], str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value["sha256"])):
            issues.append({"code": "invalid_binding", "slot_id": slot_id, "message": "素材校验摘要无效"})
        declared = next(slot.get("language") for slot in normalized["input_slots"] if slot["id"] == slot_id)
        resolved = value.get("resolved_language") or (value.get("language") if value.get("language_confirmed") else None)
        if declared and resolved and declared != resolved:
            issues.append({"code": "language_mismatch", "slot_id": slot_id, "message": "素材语言与模板输入槽声明不同"})
    if issues:
        raise GraphValidationError(issues)
    return GraphExecutionPlan(task_id=task_id, output_dir=output_dir, graph=normalized,
                              bindings=bindings, order=topological_node_ids(normalized),
                              node_snapshots=deepcopy(node_snapshots or {}))


def validate_graph_profile(profile: Any) -> dict[str, Any]:
    """Validate a public execution profile independently of its HTTP schema."""
    if (not isinstance(profile, dict) or set(profile) != {"version", "graph", "bindings"}
            or type(profile.get("version")) is not int or profile["version"] != 2):
        raise GraphValidationError([{"code": "invalid_profile", "message": "V2 执行配置只能包含 version、graph 和 bindings"}])
    plan = build_graph_plan(profile["graph"], profile["bindings"])
    return {"version": 2, "graph": plan.graph, "bindings": plan.bindings}
