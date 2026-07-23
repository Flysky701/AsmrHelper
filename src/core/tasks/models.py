"""Core task domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    task_type: str
    task_source: str
    session_id: str
    input_asset_id: str = ""
    companion_asset_ids: list[str] = field(default_factory=list)
    execution_profile: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    dedupe_key: str = ""
    created_at: str = ""


@dataclass(slots=True)
class TaskStatus:
    task_id: str
    state: str
    stage: str | None = None
    progress: float = 0.0
    message: str = ""
    detail: str = ""
    task_type: str = ""
    task_source: str = ""
    session_id: str = ""
    input_asset_id: str = ""
    created_at: str = ""
    queued_at: str | None = None
    started_at: str | None = None
    updated_at: str = ""
    finished_at: str | None = None
    error: dict[str, Any] | None = None
    artifact_set_id: str | None = None
    review_state: str = ""
    review_note: str = ""


@dataclass(slots=True)
class RuntimeEvent:
    """One diagnostic event emitted while a task is being processed."""

    sequence: int
    time: str
    level: str
    type: str
    task_id: str
    stage: str | None = None
    message: str = ""
    detail: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
