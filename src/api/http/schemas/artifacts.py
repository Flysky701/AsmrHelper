"""Canonical Pydantic schemas for artifact and task-result endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.core.artifacts import ArtifactRecord


class ArtifactResponse(BaseModel):
    artifact_id: str
    task_id: str
    type: str
    path: str
    stage: str = ""
    label: str = ""
    primary: bool = False
    preview: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls,
        record: ArtifactRecord,
        *,
        primary_artifact_id: str | None = None,
    ) -> "ArtifactResponse":
        return cls(
            artifact_id=record.artifact_id,
            task_id=record.task_id,
            type=record.artifact_type,
            path=record.path,
            stage=record.stage,
            label=record.label,
            primary=record.artifact_id == primary_artifact_id,
            preview=bool(record.preview_kind),
            metadata=dict(record.metadata),
        )


class TaskResultResponse(BaseModel):
    task_id: str
    primary_artifact_id: str | None = None
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_view(cls, view: dict[str, Any]) -> "TaskResultResponse":
        primary_artifact_id = view.get("primary_artifact_id")
        return cls(
            task_id=str(view["task_id"]),
            primary_artifact_id=primary_artifact_id,
            artifacts=[
                ArtifactResponse.from_record(
                    record,
                    primary_artifact_id=primary_artifact_id,
                )
                for record in view.get("artifacts", [])
            ],
            warnings=list(view.get("warnings", [])),
        )


class TaskPreviewResponse(TaskResultResponse):
    preview_modes: list[str] = Field(default_factory=list)
    artifact_count: int = 0

    @classmethod
    def from_view(cls, view: dict[str, Any]) -> "TaskPreviewResponse":
        result = TaskResultResponse.from_view(view)
        return cls(
            **result.model_dump(),
            preview_modes=list(view.get("preview_modes", [])),
            artifact_count=int(view.get("artifact_count", len(result.artifacts))),
        )
