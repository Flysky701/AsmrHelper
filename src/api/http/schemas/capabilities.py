"""Pydantic schemas for capability descriptor endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CapabilityOptionResponse(BaseModel):
    name: str
    type: str
    required: bool = False
    default: Any = None
    description: str = ""
    enum: list[Any] = Field(default_factory=list)
    min: float | int | None = None
    max: float | int | None = None
    advanced: bool = False
    secret: bool = False


class CapabilityRuntimeRequirementsResponse(BaseModel):
    python_modules: list[str] = Field(default_factory=list)
    system_tools: list[str] = Field(default_factory=list)


class CapabilityDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    kind: str
    supported_models: list[str]
    default_model: str | None
    common_option_schema: list[CapabilityOptionResponse]
    provider_option_schema: list[CapabilityOptionResponse]
    supports: dict[str, Any]
    runtime_requirements: CapabilityRuntimeRequirementsResponse = Field(
        default_factory=CapabilityRuntimeRequirementsResponse
    )
