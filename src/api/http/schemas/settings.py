"""Pydantic schemas for settings endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class SettingsResponse(BaseModel):
    settings: dict[str, Any]


class ConnectionRemovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=64, max_length=64)
    confirmed: StrictBool


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict, description="Partial settings update")


class SettingsValidateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict, description="Settings candidate to validate")


class SettingsValidateResponse(BaseModel):
    valid: bool
    errors: list[str]
    settings: dict[str, Any]


class ProviderTestRequest(BaseModel):
    provider: str = Field(..., description="Provider id to test")
    settings: dict[str, Any] = Field(default_factory=dict, description="Optional override settings")


class ProviderModelsResponse(BaseModel):
    provider: str
    models: list[str]


class ProviderTestResponse(BaseModel):
    provider: str
    success: bool
    error_code: str | None = None
    message: str = ""
    errors: list[str] = Field(default_factory=list)
