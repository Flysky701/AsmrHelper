"""Versioned graph values. A node ID identifies an instance, never a capability."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph_catalog import GRAPH_CATALOG as GRAPH_CATALOG


GRAPH_VERSION = 2


class GraphValidationError(ValueError):
    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__("；".join(
            f"{item.get('node_id', 'workflow')}: {item['message']}" for item in issues
        ))


@dataclass(slots=True)
class GraphExecutionPlan:
    """Validated task-local graph and bindings; internal snapshots stay outside the graph."""

    task_id: str
    output_dir: str
    graph: dict[str, Any]
    bindings: dict[str, dict[str, Any]]
    order: list[str]
    node_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def nodes_by_id(self) -> dict[str, dict[str, Any]]:
        return {node["id"]: node for node in self.graph["nodes"]}

    @property
    def used_slot_ids(self) -> set[str]:
        return {edge["source"]["slot_id"] for edge in self.graph["edges"]
                if edge["source"]["kind"] == "slot"}

    def inputs_for(self, node_id: str) -> dict[str, dict[str, str]]:
        return {edge["target"]["port"]: dict(edge["source"])
                for edge in self.graph["edges"] if edge["target"]["node_id"] == node_id}
