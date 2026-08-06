"""Pydantic schemas for model management endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSummaryResponse(BaseModel):
    model_id: str
    kind: str
    category: str
    backend: str
    display_name: str
    install_strategy: str = ""
    supports_install: bool = False
    supports_remove: bool = False
    family_id: str | None = None
    variant_group: str | None = None
    variant_tier: str | None = None
    is_primary_variant: bool = False
    dependency_group: str | None = None
    runtime_profile: str | None = None
    preferred_runtime: str | None = None
    install_modes: list[str] = Field(default_factory=list)
    default_install_mode: str | None = None
    required_assets: list[str] = Field(default_factory=list)
    recommended_assets: list[str] = Field(default_factory=list)
    required_system_tools: list[str] = Field(default_factory=list)
    supported_os: list[str] = Field(default_factory=list)


class ModelStatusIssueResponse(BaseModel):
    code: str
    requirement: str
    message: str


class ModelStatusResponse(BaseModel):
    model_id: str
    status: str
    detail: str
    executable: bool = False
    issues: list[ModelStatusIssueResponse] = Field(default_factory=list)


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
    install_mode: str = Field("single", description="Install scope: single/recommended/family_all")
    install_dependencies: bool = Field(True, description="Install required runtime dependencies when supported")
    install_recommended_assets: bool = Field(False, description="Install recommended companion assets")
    allow_fallback_variant: bool = Field(False, description="Allow family-level fallback selection when available")
