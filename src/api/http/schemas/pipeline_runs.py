"""Schemas for task-driven pipeline run endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .pipeline import ArtifactSetResponse, PipelineRunResponse


class PipelineTaskRunRequest(BaseModel):
    task_id: str = Field(..., description="Task ID for a pipeline task")


class PipelineTaskRunResponse(PipelineRunResponse):
    artifacts: ArtifactSetResponse = Field(default_factory=ArtifactSetResponse)
