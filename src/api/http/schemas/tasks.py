"""Pydantic schemas for task endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.app.dto import RuntimeEvent, TaskSpec, TaskStatus
from .artifacts import (
    ArtifactResponse,
    TaskPreviewResponse as TaskPreviewResponse,
    TaskResultResponse,
)


TaskState = Literal["pending", "running", "completed", "failed", "cancelled", "skipped"]
ReviewState = Literal["", "accepted", "needs_review", "needs_rework"]


class TaskStatusResponse(BaseModel):
    task_id: str
    state: TaskState
    stage: str | None = None
    progress: float = Field(0.0, ge=0.0, le=1.0)
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
    retry_of_task_id: str | None = None
    review_state: ReviewState = ""
    review_note: str = ""

    @classmethod
    def from_task_status(cls, task: TaskStatus) -> "TaskStatusResponse":
        return cls(
            task_id=task.task_id,
            state=task.state,
            stage=task.stage,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
            task_type=task.task_type,
            task_source=task.task_source,
            session_id=task.session_id,
            input_asset_id=task.input_asset_id,
            created_at=task.created_at,
            queued_at=task.queued_at,
            started_at=task.started_at,
            updated_at=task.updated_at,
            finished_at=task.finished_at,
            error=task.error,
            artifact_set_id=task.artifact_set_id,
            retry_of_task_id=task.retry_of_task_id,
            review_state=task.review_state,
            review_note=task.review_note,
        )


class TaskListResponse(BaseModel):
    tasks: list[TaskStatusResponse]

    @classmethod
    def from_tasks(cls, tasks: list[TaskStatus]) -> "TaskListResponse":
        return cls(tasks=[TaskStatusResponse.from_task_status(task) for task in tasks])


class RuntimeEventResponse(BaseModel):
    sequence: int = Field(ge=1)
    time: str
    level: str
    type: str
    task_id: str
    stage: str | None = None
    message: str = ""
    detail: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_runtime_event(cls, event: RuntimeEvent) -> "RuntimeEventResponse":
        return cls(
            sequence=event.sequence,
            time=event.time,
            level=event.level,
            type=event.type,
            task_id=event.task_id,
            stage=event.stage,
            message=event.message,
            detail=event.detail,
            data=dict(event.data),
        )


class TaskCreateRequest(BaseModel):
    task_type: str
    task_source: str = "manual"
    session_id: str
    input_asset_id: str = ""
    companion_asset_ids: list[str] = Field(default_factory=list)
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    dedupe_key: str = ""


class TaskSpecResponse(BaseModel):
    task_id: str
    task_type: str
    task_source: str
    session_id: str
    input_asset_id: str = ""
    companion_asset_ids: list[str] = Field(default_factory=list)
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    dedupe_key: str = ""
    retry_of_task_id: str | None = None
    created_at: str = ""

    @classmethod
    def from_task_spec(cls, task: TaskSpec) -> "TaskSpecResponse":
        return cls(
            task_id=task.task_id,
            task_type=task.task_type,
            task_source=task.task_source,
            session_id=task.session_id,
            input_asset_id=task.input_asset_id,
            companion_asset_ids=list(task.companion_asset_ids),
            execution_profile=dict(task.execution_profile),
            priority=task.priority,
            dedupe_key=task.dedupe_key,
            retry_of_task_id=task.retry_of_task_id,
            created_at=task.created_at,
        )


class TaskCreateResponse(BaseModel):
    task: TaskStatusResponse
    spec: TaskSpecResponse


class TaskBatchCreateItemRequest(BaseModel):
    task_type: str
    task_source: str = "manual"
    session_id: str
    input_asset_id: str = ""
    companion_asset_ids: list[str] = Field(default_factory=list)
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    dedupe_key: str = ""


class TaskBatchCreateRequest(BaseModel):
    items: list[TaskBatchCreateItemRequest] = Field(default_factory=list)


class TaskBatchCreateResponse(BaseModel):
    items: list[TaskCreateResponse] = Field(default_factory=list)


ArtifactRecordResponse = ArtifactResponse
TaskArtifactsResponse = TaskResultResponse


class ReviewUpdateRequest(BaseModel):
    review_state: ReviewState


class ReviewNoteUpdateRequest(BaseModel):
    review_note: str = ""


class TaskQueueStatsResponse(BaseModel):
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    skipped: int = 0
    max_concurrent: int = 0
    can_start: bool = True


class TaskQueueSnapshotResponse(BaseModel):
    queued_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    running_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    completed_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    failed_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    cancelled_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    skipped_tasks: list[TaskStatusResponse] = Field(default_factory=list)
    queue_stats: TaskQueueStatsResponse
