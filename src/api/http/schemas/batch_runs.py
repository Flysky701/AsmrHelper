"""Schemas for persistent batch-run endpoints."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from src.core.batches import BatchRunItem, BatchRunRecord

from .pipeline_runs import PipelineExecutionProfileRequest, PipelineOutputRequest
from .workflow_graph import GraphDefinitionRequest, GraphMaterialBindingRequest


BatchRunState = Literal[
    "pending",
    "running",
    "cancelling",
    "completed",
    "completed_with_errors",
    "cancelled",
    "interrupted",
    "history_deleted",
]


class BatchDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(..., min_length=1)
    recursive: bool = True
    limit: int | None = Field(None, ge=1, le=501)
    media_kind: Literal["audio", "subtitle", "all"] = "audio"


class BatchDiscoveredFileResponse(BaseModel):
    path: str
    name: str
    size_bytes: int = Field(ge=0)
    kind: Literal["audio", "subtitle"] = "audio"
    companion_paths: list[str] = Field(default_factory=list)
    companion_subtitles: list[dict[str, Any]] = Field(default_factory=list)


class BatchDiscoverResponse(BaseModel):
    directory: str
    files: list[BatchDiscoveredFileResponse] = Field(default_factory=list)


class BatchRunInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    companion_paths: list[str] = Field(default_factory=list)


class BatchGraphProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2]
    graph: GraphDefinitionRequest


class BatchRunGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    label: str = Field("", max_length=100)
    bindings: dict[str, GraphMaterialBindingRequest]


class BatchRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("", max_length=100)
    inputs: list[BatchRunInputRequest] = Field(default_factory=list, max_length=500)
    groups: list[BatchRunGroupRequest] = Field(default_factory=list, max_length=500)
    client_request_id: str | None = Field(None, min_length=1, max_length=100)
    output: PipelineOutputRequest = Field(default_factory=PipelineOutputRequest)
    execution_profile: Annotated[PipelineExecutionProfileRequest | BatchGraphProfileRequest,
                                 Field(discriminator="version")] = Field(
        default_factory=PipelineExecutionProfileRequest
    )
    max_parallel: int = Field(1, ge=1, le=4)

    @field_validator("execution_profile", mode="before")
    @classmethod
    def legacy_version_default(cls, value):
        if isinstance(value, dict) and "version" not in value and "graph" not in value:
            return {"version": 1, **value}
        return value

    @model_validator(mode="after")
    def validate_batch_shape(self):
        if self.execution_profile.version == 2:
            if not self.groups or self.inputs:
                raise ValueError("graph batches require explicit groups and no legacy inputs")
            ids = [group.group_id for group in self.groups]
            if len(set(ids)) != len(ids):
                raise ValueError("group_id must be unique within the batch")
        elif not self.inputs or self.groups:
            raise ValueError("version 1 batches require inputs and no graph groups")
        return self


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
    group_id: str | None = None
    label: str = ""
    bindings: dict[str, Any] = Field(default_factory=dict)
    retry_available: bool = False
    retry_blocked_reason: str | None = None
    removed: bool = False

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
            group_id=item.group_id,
            label=item.label,
            bindings=dict(item.bindings),
            retry_available=item.state in {"failed", "cancelled"} and not item.retry_blocked_reason,
            retry_blocked_reason=item.retry_blocked_reason,
            removed=item.removed,
        )


class BatchItemRemovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: str = Field(min_length=1)
    confirmed: StrictBool


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
    history_deleted_count: int = 0
    items: list[BatchRunItemResponse]
    client_request_id: str | None = None
    retry_available: bool = False
    retry_blocked_reason: str | None = None

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
                "history_deleted",
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
            history_deleted_count=counts["history_deleted"],
            items=[BatchRunItemResponse.from_item(item) for item in record.items],
            client_request_id=record.client_request_id,
            retry_available=record.state in {"completed_with_errors", "cancelled", "interrupted"}
                and any(item.state in {"failed", "cancelled"} for item in record.items)
                and not record.retry_blocked_reason,
            retry_blocked_reason=record.retry_blocked_reason,
        )


class BatchRunListResponse(BaseModel):
    batches: list[BatchRunResponse]
