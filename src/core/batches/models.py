"""Persistent facts for one user-visible batch run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BatchRunItem:
    item_id: str
    input_path: str
    companion_paths: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    current_task_id: str | None = None
    state: str = "pending"
    progress: float = 0.0
    message: str = ""
    output_path: str = ""
    error: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchRunItem":
        return cls(
            item_id=str(payload["item_id"]),
            input_path=str(payload["input_path"]),
            companion_paths=list(payload.get("companion_paths") or []),
            task_ids=list(payload.get("task_ids") or []),
            current_task_id=payload.get("current_task_id"),
            state=str(payload.get("state") or "pending"),
            progress=float(payload.get("progress") or 0.0),
            message=str(payload.get("message") or ""),
            output_path=str(payload.get("output_path") or ""),
            error=dict(payload["error"]) if isinstance(payload.get("error"), dict) else None,
        )


@dataclass(slots=True)
class BatchRunRecord:
    batch_id: str
    name: str
    state: str
    progress: float
    created_at: str
    updated_at: str
    finished_at: str | None
    output_dir: str
    execution_profile: dict[str, Any]
    max_parallel: int
    items: list[BatchRunItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BatchRunRecord":
        return cls(
            batch_id=str(payload["batch_id"]),
            name=str(payload.get("name") or payload["batch_id"]),
            state=str(payload.get("state") or "pending"),
            progress=float(payload.get("progress") or 0.0),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            finished_at=payload.get("finished_at"),
            output_dir=str(payload.get("output_dir") or ""),
            execution_profile=dict(payload.get("execution_profile") or {}),
            max_parallel=max(1, int(payload.get("max_parallel") or 1)),
            items=[BatchRunItem.from_dict(item) for item in payload.get("items") or []],
        )
