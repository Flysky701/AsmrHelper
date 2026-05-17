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
