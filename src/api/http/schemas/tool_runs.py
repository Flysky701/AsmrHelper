"""Schemas for task-driven tool run endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolTaskCreateRequest(BaseModel):
    task_type: str = Field(..., min_length=1)
    input_path: str = Field(..., min_length=1)
    companion_paths: list[str] = Field(default_factory=list)
    execution_profile: dict[str, Any] = Field(default_factory=dict)


class ToolDescriptorResponse(BaseModel):
    task_type: str
    name: str
    category: str
    primary_artifact: str = ""


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptorResponse] = Field(default_factory=list)
