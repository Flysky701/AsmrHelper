"""Schemas for task-driven tool run endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolTaskRunRequest(BaseModel):
    task_id: str = Field(..., description="Task ID for a tool task")


class ToolDescriptorResponse(BaseModel):
    task_type: str
    name: str
    category: str
    primary_artifact: str = ""


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptorResponse] = Field(default_factory=list)
