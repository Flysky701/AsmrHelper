"""Pydantic schemas for settings endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    settings: dict[str, Any]


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


class ProviderTestResponse(BaseModel):
    provider: str
    success: bool
    errors: list[str] = Field(default_factory=list)
