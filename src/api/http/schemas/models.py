"""Pydantic schemas for model management endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSummaryResponse(BaseModel):
    model_id: str
    kind: str
    category: str
    backend: str
    display_name: str


class ModelStatusResponse(BaseModel):
    model_id: str
    status: str
    detail: str


class ModelOperationResponse(BaseModel):
    action: str
    model_id: str
    success: bool
    status: str
    detail: str


class ModelVerificationResponse(BaseModel):
    model_id: str
    success: bool
    status: str
    detail: str


class ModelInstallRequest(BaseModel):
    mirror: str | None = Field(None, description="HuggingFace mirror URL")
    force: bool = Field(False, description="Force reinstall even if already installed")
