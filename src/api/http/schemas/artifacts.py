"""Pydantic schemas for artifact endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ArtifactRecordResponse(BaseModel):
    artifact_id: str
    task_id: str
    artifact_type: str
    path: str
    label: str = ""
    preview_kind: str = ""
    stage: str = ""
    is_primary: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactSetResponse(BaseModel):
    task_id: str
    files: dict[str, str] = Field(default_factory=dict)
    primary_output: str | None = None
    entries: list[ArtifactRecordResponse] = Field(default_factory=list)


class TaskResultViewResponse(BaseModel):
    task_id: str
    primary_output: ArtifactRecordResponse | None = None
    secondary_outputs: list[ArtifactRecordResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
