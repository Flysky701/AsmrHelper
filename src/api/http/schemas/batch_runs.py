"""Schemas for persistent batch-run endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.batches import BatchRunItem, BatchRunRecord

from .pipeline_runs import PipelineExecutionProfileRequest, PipelineOutputRequest


BatchRunState = Literal[
    "pending",
    "running",
    "cancelling",
    "completed",
    "completed_with_errors",
    "cancelled",
    "interrupted",
]


class BatchDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(..., min_length=1)
    recursive: bool = True


class BatchDiscoveredFileResponse(BaseModel):
    path: str
    name: str
    size_bytes: int = Field(ge=0)
    companion_paths: list[str] = Field(default_factory=list)


class BatchDiscoverResponse(BaseModel):
    directory: str
    files: list[BatchDiscoveredFileResponse] = Field(default_factory=list)


class BatchRunInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    companion_paths: list[str] = Field(default_factory=list)


class BatchRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("", max_length=100)
    inputs: list[BatchRunInputRequest] = Field(min_length=1, max_length=500)
    output: PipelineOutputRequest = Field(default_factory=PipelineOutputRequest)
    execution_profile: PipelineExecutionProfileRequest = Field(
        default_factory=PipelineExecutionProfileRequest
    )
    max_parallel: int = Field(1, ge=1, le=4)


class BatchRunItemResponse(BaseModel):
    item_id: str
    input_path: str
    companion_paths: list[str]
    task_ids: list[str]
    current_task_id: str | None
    state: str
    progress: float = Field(ge=0.0, le=1.0)
    message: str
    output_path: str
    error: dict[str, Any] | None

    @classmethod
    def from_item(cls, item: BatchRunItem) -> "BatchRunItemResponse":
        return cls(
            item_id=item.item_id,
            input_path=item.input_path,
            companion_paths=list(item.companion_paths),
            task_ids=list(item.task_ids),
            current_task_id=item.current_task_id,
            state=item.state,
            progress=item.progress,
            message=item.message,
            output_path=item.output_path,
            error=dict(item.error) if item.error else None,
        )


class BatchRunResponse(BaseModel):
    batch_id: str
    name: str
    state: BatchRunState
    progress: float = Field(ge=0.0, le=1.0)
    created_at: str
    updated_at: str
    finished_at: str | None
    output_dir: str
    max_parallel: int
    total_count: int
    pending_count: int
    running_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    skipped_count: int
    items: list[BatchRunItemResponse]

    @classmethod
    def from_record(cls, record: BatchRunRecord) -> "BatchRunResponse":
        counts = {
            state: sum(item.state == state for item in record.items)
            for state in (
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                "skipped",
            )
        }
        return cls(
            batch_id=record.batch_id,
            name=record.name,
            state=record.state,
            progress=record.progress,
            created_at=record.created_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
            output_dir=record.output_dir,
            max_parallel=record.max_parallel,
            total_count=len(record.items),
            pending_count=counts["pending"],
            running_count=counts["running"],
            completed_count=counts["completed"],
            failed_count=counts["failed"],
            cancelled_count=counts["cancelled"],
            skipped_count=counts["skipped"],
            items=[BatchRunItemResponse.from_item(item) for item in record.items],
        )


class BatchRunListResponse(BaseModel):
    batches: list[BatchRunResponse]
