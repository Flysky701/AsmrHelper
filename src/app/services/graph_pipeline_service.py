"""V2 graph submission facts and adapters for the existing task services.

Graph definitions stay portable. Material identities and speech snapshots belong
to a single submitted run; private translation credentials stay in TaskService.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from src.core.orchestration.pipeline.graph_validation import build_graph_plan
from src.core.orchestration.pipeline.models import PipelineExecutionContext
from src.core.orchestration.pipeline.planner import build_execution_plan
from src.core.orchestration.pipeline.workflow import subtitle_material
from src.core.subtitles.translation_reuse import audio_duration
from src.app.persistence.recovery_store import file_identity

STAGES = ("separate", "asr", "align", "translate", "tts", "mix", "export")


@dataclass(frozen=True)
class FrozenGraphSubmission:
    """Process-local prepared facts, never a runnable task or a public payload."""

    profile: dict
    connections: dict
    speech_connections: dict

    @property
    def paths(self) -> list[str]:
        return list(self.profile["_graph_runtime"]["asset_identities"])


def freeze_graph_connections(profile: dict, settings: dict | None = None) -> tuple[dict, dict]:
    """Capture selected translation instances without creating task identities."""
    from src.config import config
    from src.task_connection_context import capture_connections, resolve_task_settings

    result = deepcopy(profile)
    settings = config.to_dict() if settings is None else deepcopy(settings)
    connections = {}
    for node in result["graph"]["nodes"]:
        if node["kind"] != "translate":
            continue
        if not node.get("options", {}).get("connection_ref"):
            raise ValueError(f"node {node['id']} requires an explicit translation connection")
        selected = resolve_task_settings(settings, node_profile(node))
        connections[node["id"]] = capture_connections(selected)
        if node.get("model") in (None, "", "default"):
            node["model"] = selected["api"].get(f"{node['provider']}_model")
        if not node.get("model"):
            raise ValueError(f"node {node['id']} requires an explicit translation model")
    return result, connections


def capture_graph_speech_connections(profile: dict) -> dict:
    """Retain private credential evidence for immutable speech connection refs."""
    snapshots = profile.get("_graph_runtime", {}).get("node_snapshots", {})
    contexts = {}
    for node in profile["graph"]["nodes"]:
        if node["kind"] == "tts":
            from .speech_service import get_speech_service
            if node["id"] not in snapshots:
                raise ValueError("frozen speech snapshot unavailable; submit a new batch")
            contexts[node["id"]] = get_speech_service().connection_context(
                snapshots[node["id"]]["connection"])
    return deepcopy(contexts)


def validate_frozen_graph_submission(submission: FrozenGraphSubmission) -> dict:
    """Recheck original facts; never replace snapshots with current selections."""
    if not isinstance(submission, FrozenGraphSubmission):
        raise ValueError("frozen graph submission unavailable; submit a new batch")
    profile = submission.profile
    runtime = profile.get("_graph_runtime", {})
    if not runtime.get("asset_identities"):
        raise ValueError("frozen material identities unavailable; submit a new batch")
    translations = {node["id"] for node in profile["graph"]["nodes"] if node["kind"] == "translate"}
    if translations != set(submission.connections):
        raise ValueError("frozen translation context unavailable; submit a new batch")
    prepared, _ = prepare_graph_profile(profile, declared_paths=submission.paths)
    if capture_graph_speech_connections(prepared) != submission.speech_connections:
        raise ValueError("frozen speech credentials changed; submit a new batch")
    return prepared


def node_profile(node: dict, snapshot: dict | None = None) -> dict:
    """A single capability projection, never a second graph execution plan."""
    stages = {kind: {"enabled": False, "provider": "unused", "options": {},
                     "provider_options": {}} for kind in STAGES}
    stage = {key: deepcopy(node[key]) for key in ("provider", "model", "options", "provider_options")
             if key in node}
    stage.update(enabled=True)
    stage.setdefault("options", {})
    stage.setdefault("provider_options", {})
    if node["kind"] == "align" and stage.get("model") == "default":
        stage["model"] = "qwen3-forced-aligner-0.6b"
    if node["kind"] == "tts" and not stage["options"].get("speech_recipe_id"):
        stage["options"]["language"] = node.get("target_lang") or "auto"
    if node["kind"] == "tts" and snapshot:
        stage.update(provider=snapshot["recipe"]["provider_id"], model=snapshot["recipe"]["model"],
                     provider_options={"speech_snapshot": deepcopy(snapshot)})
    stages[node["kind"]] = stage
    return {"version": 1, "source_lang": node.get("source_lang") or "ja",
            "target_lang": node.get("target_lang") or "zh", "skip_existing": False, "stages": stages}


def prepare_graph_profile(profile: dict, *, declared_paths: list[str] | None = None) -> tuple[dict, dict]:
    """Validate selected local materials and pin them, without probing any engine."""
    from src.core.orchestration.pipeline.graph_adapters import GraphValue

    result = deepcopy(profile)
    plan = build_graph_plan(result["graph"], result.get("bindings", {}))
    graph = plan.graph
    declared = None if declared_paths is None else {str(Path(p).resolve()).casefold() for p in declared_paths if p}
    identities, values = {}, {}

    def identity(path):
        resolved = str(Path(path).expanduser().resolve())
        if declared is not None and resolved.casefold() not in declared:
            raise ValueError("图绑定的素材未包含在本次输入中，请明确添加素材")
        if resolved not in identities:
            identities[resolved] = file_identity(resolved)
        return resolved, identities[resolved]

    for slot in graph["input_slots"]:
        if slot["id"] not in plan.used_slot_ids:
            continue
        binding = deepcopy(result["bindings"][slot["id"]])
        path, fact = identity(binding["path"])
        metadata = {"timeline_id": fact["sha256"], "pair_confirmed": True}
        if slot["type"] == "audio":
            duration = audio_duration(path)
            if duration is None or duration <= 0:
                raise ValueError(f"输入槽 {slot['id']} 无法验证音频时长")
            metadata["duration"] = duration
            value = GraphValue(kind="audio", path=path, metadata=metadata)
        else:
            binding["path"] = path
            segments, language = subtitle_material(binding)
            if slot.get("language") and slot["language"] != language:
                raise ValueError(f"输入槽 {slot['id']} 的字幕语言与声明不符")
            metadata.update(language=language, duration=max(s["end"] for s in segments))
            value = GraphValue(kind="subtitle", path=path, segments=segments, metadata=metadata)
        if binding.get("audio_path"):
            paired, paired_fact = identity(binding["audio_path"])
            if binding.get("pair_confirmed") is not True:
                raise ValueError(f"输入槽 {slot['id']} 尚未确认与音频对应")
            duration = audio_duration(paired)
            if duration is None or (slot["type"] == "subtitle" and metadata["duration"] > duration + 0.1):
                raise ValueError(f"输入槽 {slot['id']} 时间轴超出对应音频")
            metadata.update(timeline_id=paired_fact["sha256"], pair_confirmed=True)
            if slot["type"] == "subtitle":
                metadata["duration"] = duration
        values[slot["id"]] = value
    runtime = deepcopy(result.get("_graph_runtime", {}))
    if runtime.get("asset_identities") is not None and runtime["asset_identities"] != identities:
        raise ValueError("图任务素材在提交后改变，请检查并重新提交")
    runtime["asset_identities"] = identities
    result.update(graph=graph, _graph_runtime=runtime)
    _check_material_facts(graph, values)
    return result, values


def _check_material_facts(graph: dict, values: dict) -> None:
    """Reject known input contradictions before freezing or invoking providers.

    Only subtitle ports supply subtitle-language evidence. Timeline provenance
    propagates through future node outputs, so an invalid merge is not deferred
    until after potentially paid upstream synthesis. Actual output durations are
    still inspected and checked by the runtime adapter.
    """
    from src.core.orchestration.pipeline.graph_validation import build_graph_plan

    plan = build_graph_plan(graph, {slot["id"]: {"path": "validated"} for slot in graph["input_slots"]})
    nodes = {node["id"]: node for node in graph["nodes"]}
    facts = {}
    for node_id in plan.order:
        node = nodes[node_id]
        incoming = {}
        for port, ref in plan.inputs_for(node_id).items():
            incoming[port] = (values[ref["slot_id"]].metadata if ref["kind"] == "slot"
                              else facts[ref["node_id"]])
            if node["kind"] == "audio_export" and ref["kind"] == "slot":
                from src.utils.constants import AUDIO_EXTENSIONS
                if Path(values[ref["slot_id"]].path).suffix.lower() not in AUDIO_EXTENSIONS:
                    raise ValueError(f"节点 {node_id} 音频导出仅支持现有音频格式，保留原格式且不转码")
        language = incoming.get("subtitle", {}).get("language")
        if node["kind"] in {"translate", "align"} and language != node.get("source_lang"):
            raise ValueError(f"节点 {node_id} 缺少匹配源语言的字幕")
        if node["kind"] == "tts" and language != node.get("target_lang"):
            raise ValueError(f"节点 {node_id} 缺少目标语言字幕，请自行连接翻译或更换素材")
        if node["kind"] in {"align", "mix"}:
            audio = incoming["audio"]
            other = incoming["subtitle" if node["kind"] == "align" else "speech"]
            if (not audio.get("timeline_id") or audio.get("timeline_id") != other.get("timeline_id")
                    or audio.get("pair_confirmed") is not True or other.get("pair_confirmed") is not True):
                raise ValueError(f"节点 {node_id} 的素材尚未确认属于同一录音和时间轴")
        source_port = "audio" if node["kind"] in {"separate", "asr", "mix", "audio_export"} else "subtitle"
        facts[node_id] = deepcopy(incoming[source_port])
        if node["kind"] == "asr":
            facts[node_id]["language"] = node["source_lang"]
        elif node["kind"] == "translate":
            facts[node_id]["language"] = node["target_lang"]


def freeze_graph_speech(profile: dict) -> dict:
    result = deepcopy(profile)
    snapshots = result.setdefault("_graph_runtime", {}).setdefault("node_snapshots", {})
    for node in result["graph"]["nodes"]:
        if node["kind"] != "tts":
            continue
        from .speech_service import get_speech_service
        speech = get_speech_service()
        snapshot = snapshots.get(node["id"])
        if snapshot is None:
            snapshot = speech.pipeline_snapshot(node_profile(node)["stages"]["tts"])
            # Auto is a portable recipe preference; a newly submitted node has
            # an explicit output language. Freeze that choice only in this run.
            # Existing task snapshots and the saved recipe remain unchanged.
            if snapshot["recipe"].get("language", "auto") == "auto":
                snapshot = deepcopy(snapshot)
                snapshot["recipe"]["language"] = node["target_lang"]
        language = snapshot["recipe"].get("language", "auto")
        if language not in ("auto", node.get("target_lang")):
            raise ValueError(f"节点 {node['id']} 的声音规则语言与目标字幕不一致")
        snapshots[node["id"]] = snapshot
    return result


def make_node_plan(node: dict, *, task_id: str, output_dir: str, snapshots: dict):
    if node["kind"] == "audio_export":
        # This graph-only operation copies a validated audio value; it has no
        # legacy engine plan, model, connection or implicit upstream stages.
        return None
    return build_execution_plan(PipelineExecutionContext(
        task_id=task_id, input_path="", output_dir=output_dir,
        execution_profile=node_profile(node, snapshots.get(node["id"]))))


def run_graph_task(service, task_spec, *, progress_callback=None, cancel_event=None, manage_lifecycle=True):
    """Run one V2 task through the same lifecycle and artifact index as V1."""
    from contextlib import nullcontext
    from src.app.dto import PipelineResult
    from src.app.errors import AppExecutionError, ResourceValidationError
    from src.core.orchestration.pipeline.graph_adapters import GraphStageRunner
    from src.core.orchestration.pipeline.graph_executor import GraphExecutor

    tasks = service._task_service
    task_id, current_node = task_spec.task_id, "prepare"
    session = service._session_service.get_session(task_spec.session_id)
    primary = service._input_catalog_service.get_asset(task_spec.input_asset_id)
    paths = [primary.absolute_path, *[service._input_catalog_service.get_asset(a).absolute_path
                                    for a in session.companion_asset_ids]]
    if manage_lifecycle:
        tasks.start_task(task_id, message="running graph", stage=current_node)

    def node_context(node):
        return (tasks.graph_node_connection_context(task_id, node["id"])
                if node["kind"] == "translate" else nullcontext())

    def on_stage(node_id, progress, message):
        nonlocal current_node
        current_node = node_id
        tasks.update_progress(task_id, progress, message=message, stage=node_id)
        if progress_callback:
            progress_callback(message)

    try:
        profile, slots = prepare_graph_profile(task_spec.execution_profile, declared_paths=paths)
        issues = service._resource_service._check_graph_profile(profile, node_context=node_context)
        if issues:
            raise ResourceValidationError("；".join(f"{i['stage']}: {i['message']}" for i in issues))
        workspace = service._resource_service.ensure_workspace()
        output_dir = service._resolve_task_output_dir(task_id=task_id, input_path=primary.absolute_path,
            execution_profile=profile, session_output_root=session.resolved_output_dir,
            workspace_output_root=str(workspace["output_dir"]))
        snapshots = profile.get("_graph_runtime", {}).get("node_snapshots", {})
        plan = build_graph_plan(profile["graph"], profile["bindings"], task_id=task_id,
                                output_dir=output_dir, node_snapshots=snapshots)
        results = GraphExecutor(stage_runner=GraphStageRunner(service._executor)).execute(
            plan, slot_values=slots,
            plan_for_node=lambda node: make_node_plan(node, task_id=task_id, output_dir=output_dir,
                                                     snapshots=snapshots),
            node_context=node_context, stage_callback=on_stage, cancel_event=cancel_event)
        service._register_pipeline_artifacts(task_id=task_id, results=results,
                                             mix_path=None, exported_subtitle=None)
        if manage_lifecycle:
            tasks.complete_task(task_id, message="graph completed", detail=results["primary_output"],
                                stage=current_node, artifact_set_id=task_id)
        status = tasks.get_task(task_id)
        return PipelineResult(success=True, input_path=primary.absolute_path, task=status,
            task_id=task_id, task_state=status.state, artifacts=service._artifact_service.get_task_artifacts(task_id),
            steps=results["steps"], total_duration=results["total_duration"])
    except Exception as exc:
        cancelled = bool(cancel_event and cancel_event.is_set()) or isinstance(exc, InterruptedError)
        incoming_error = getattr(exc, "task_error", {})
        node_id = incoming_error.get("node_id", getattr(exc, "node_id", current_node))
        detail = str(exc)
        task_error = {"code": "GRAPH_NODE_FAILED", "stage": node_id, "node_id": node_id,
                      "message": detail, "detail": detail, "retryable": True}
        original = getattr(exc, "cause", exc)
        if incoming_error:
            task_error.update(incoming_error, stage=node_id, node_id=node_id)
        if getattr(original, "task_error", None):
            task_error.update(original.task_error, stage=node_id, node_id=node_id)
        if manage_lifecycle:
            if cancelled:
                tasks.cancel_task(task_id, message="用户取消图任务")
            else:
                tasks.fail_task(task_id, message=detail, detail=detail, stage=node_id, error=task_error)
        error = AppExecutionError(detail)
        error.task_error = task_error
        raise error from exc
