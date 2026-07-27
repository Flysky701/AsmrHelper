"""Pydantic schemas for resource endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceStatusResponse(BaseModel):
    name: str
    available: bool
    detail: str = ""
    metadata: dict = Field(default_factory=dict)


class ResourceStatusListResponse(BaseModel):
    resources: list[ResourceStatusResponse]


class RuntimeResourcesResponse(BaseModel):
    resources: dict[str, str] = Field(default_factory=dict)


class RuntimeCapabilitiesResponse(BaseModel):
    resources: dict[str, str] = Field(default_factory=dict)
    checks: list[ResourceStatusResponse] = Field(default_factory=list)


class TaskReadinessRequest(BaseModel):
    task_type: str
    execution_profile: dict = Field(default_factory=dict)


class TaskReadinessIssueResponse(BaseModel):
    stage: str
    category: str
    provider: str
    model: str | None = None
    code: str
    requirement: str
    message: str
    action: str = "engines"


class TaskReadinessResponse(BaseModel):
    task_type: str
    ready: bool
    missing_requirements: list[str] = Field(default_factory=list)
    issues: list[TaskReadinessIssueResponse] = Field(default_factory=list)
    execution_profile: dict = Field(default_factory=dict)
