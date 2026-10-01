"""Serial execution of a validated acyclic graph with instance-scoped values."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import re
import time

from .graph_adapters import GraphStageRunner, GraphValue


class GraphExecutionError(RuntimeError):
    def __init__(self, node, cause, results):
        super().__init__(f"{node['id']} ({node['kind']}) 执行失败: {cause}")
        self.node_id = node["id"]
        self.cause = cause
        self.results = results
        self.task_error = {
            "code": "GRAPH_NODE_FAILED", "stage": node["kind"], "node_id": node["id"],
            "message": str(self), "detail": str(cause), "retryable": True,
        }
        if isinstance(getattr(cause, "task_error", None), dict):
            self.task_error.update(deepcopy(cause.task_error))
            self.task_error.update(stage=node["kind"], node_id=node["id"])


class GraphExecutor:
    def __init__(self, stage_runner=None):
        self.stage_runner = stage_runner or GraphStageRunner()

    def execute(
        self, plan, *, slot_values, plan_for_node, node_context=None,
        stage_callback=None, cancel_event=None,
    ):
        """Execute each node once; no caching, implicit stages, or checkpoint resume.

        plan_for_node(node) supplies frozen provider settings as a legacy stage
        plan. node_context(node) optionally binds that instance's private LLM
        connection. Neither callback may change the graph or another node.
        """
        from .graph_validation import build_graph_plan
        from .graph_catalog import GRAPH_CATALOG

        # Do not trust a manually constructed plan's order or edge lookup.
        plan = build_graph_plan(
            plan.graph, plan.bindings, task_id=plan.task_id, output_dir=plan.output_dir,
            node_snapshots=plan.node_snapshots,
        )
        nodes = plan.nodes_by_id
        if len({node_id.casefold() for node_id in nodes}) != len(nodes):
            raise ValueError("节点 ID 大小写冲突，会覆盖 Windows 产物目录")
        slots = {slot["id"]: slot for slot in plan.graph["input_slots"]}
        values = {}
        for slot_id, slot in slots.items():
            if slot_id not in plan.used_slot_ids:
                continue
            value = slot_values.get(slot_id)
            if not isinstance(value, GraphValue) or value.kind != slot["type"]:
                raise ValueError(f"输入槽 {slot_id} 缺少已验证的 {slot['type']} 素材")
            values[("slot", slot_id)] = value.clone()
        root = Path(plan.output_dir).resolve()
        node_root = root / "nodes"
        if node_root.resolve().parent != root:
            raise ValueError("节点产物根目录越界")
        node_root.mkdir(parents=True, exist_ok=True)
        results = {
            "input": next((value.path for value in values.values() if value.path), ""),
            "output_dir": str(root), "steps": {}, "step_errors": {},
            "node_states": {node_id: "pending" for node_id in plan.order},
            "workflow_outputs": [], "primary_output": None, "total_steps": len(plan.order),
            "total_duration": 0.0, "error": None,
        }
        started = time.perf_counter()

        def report(node_id, position, message):
            if stage_callback:
                stage_callback(node_id, position / max(len(plan.order), 1), message)

        for index, node_id in enumerate(plan.order):
            node = deepcopy(nodes[node_id])
            # IDs also become directory names. Keep the safety check local even
            # when the public graph contract has already validated them.
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
                raise ValueError("节点 ID 不适合作为独立产物目录")
            # Prefix avoids Windows reserved device names such as CON/PRN.
            directory = node_root / f"node-{node_id}"
            if directory.resolve().parent != node_root.resolve():
                raise ValueError("节点产物目录越界")
            node_started = time.perf_counter()
            try:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("用户取消操作")
                results["node_states"][node_id] = "running"
                results["last_stage"] = node_id
                report(node_id, index, f"正在执行 {node_id} · {node['kind']}")
                inputs = {}
                for port, source in plan.inputs_for(node_id).items():
                    key = (("slot", source["slot_id"]) if source["kind"] == "slot"
                           else (source["node_id"], source["port"]))
                    if key not in values:
                        raise ValueError(f"节点 {node_id} 的 {port} 输入尚未产生")
                    inputs[port] = values[key].clone()
                node_plan = plan_for_node(deepcopy(node))
                context = node_context(deepcopy(node)) if node_context else nullcontext()
                with context:
                    outputs = self.stage_runner.run(
                        node, inputs, node_plan, directory, cancel_event=cancel_event,
                    )
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("用户取消操作")
                expected = GRAPH_CATALOG[node["kind"]]["outputs"]
                if set(outputs) != set(expected):
                    raise RuntimeError("节点产物端口不符合能力定义")
                output_paths = {}
                for port, kind in expected.items():
                    value = outputs[port]
                    if not isinstance(value, GraphValue) or value.kind != kind or not value.path:
                        raise RuntimeError("节点返回错误的产物类型")
                    path = Path(value.path).resolve()
                    if not path.is_relative_to(directory.resolve()):
                        raise RuntimeError("节点返回了其他实例或输入素材的路径")
                    if not path.is_file() or path.stat().st_size == 0:
                        raise RuntimeError("节点未产生有效文件")
                    values[(node_id, port)] = value.clone()
                    output_paths[port] = str(path)
                results["steps"][node_id] = {
                    "node_id": node_id, "kind": node["kind"], "state": "completed",
                    "duration": time.perf_counter() - node_started, "outputs": output_paths,
                }
                results["node_states"][node_id] = "completed"
                report(node_id, index + 1, f"已完成 {node_id} · {node['kind']}")
            except Exception as exc:
                cancelled = isinstance(exc, InterruptedError) or bool(cancel_event and cancel_event.is_set())
                state = "cancelled" if cancelled else "failed"
                results["node_states"][node_id] = state
                results["steps"][node_id] = {
                    "node_id": node_id, "kind": node["kind"], "state": state,
                    "duration": time.perf_counter() - node_started,
                }
                results["step_errors"][node_id] = str(exc)
                for later in plan.order[index + 1:]:
                    results["node_states"][later] = "blocked"
                results["error"] = str(exc)
                results["total_duration"] = time.perf_counter() - started
                raise GraphExecutionError(node, exc, results) from exc
        for selected in plan.graph["outputs"]:
            node_id, port = selected["node_id"], selected["port"]
            value = values[(node_id, port)]
            kind = nodes[node_id]["kind"]
            suffix = Path(value.path).suffix.lower().lstrip(".")
            artifact_type = f"subtitle.{suffix}" if value.kind == "subtitle" else {
                "separate": "audio.vocals", "tts": "audio.tts", "mix": "audio.mix",
            }[kind]
            metadata = {key: deepcopy(item) for key, item in value.metadata.items()
                        if key in {"language", "duration", "timeline_id", "pair_confirmed",
                                   "sample_rate", "channels"}}
            metadata.update(node_id=node_id, port=port)
            results["workflow_outputs"].append({
                "node_id": node_id, "port": port, "stage": kind, "type": artifact_type,
                "path": value.path, "preview": value.kind,
                "label": selected.get("label") or f"{node_id} · {port}", "metadata": metadata,
            })
        if results["workflow_outputs"]:
            results["primary_output"] = results["workflow_outputs"][0]["path"]
        results["total_duration"] = time.perf_counter() - started
        return results
