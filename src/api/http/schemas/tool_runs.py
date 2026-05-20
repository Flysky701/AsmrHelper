"""Schemas for task-driven tool run endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .tasks import TaskStatusResponse


class ToolTaskRunRequest(BaseModel):
    task_id: str = Field(..., description="Task ID for a tool task")


class ToolTaskRunResponse(BaseModel):
    task: TaskStatusResponse
    tool_name: str
    summary: dict[str, Any] = Field(default_factory=dict)


class ToolDescriptorResponse(BaseModel):
    task_type: str
    name: str
    category: str
    primary_artifact: str = ""


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptorResponse] = Field(default_factory=list)
