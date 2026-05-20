"""Schemas for processing session endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionOutputPolicyRequest(BaseModel):
    mode: str = "workspace-default"
    custom_output_dir: str | None = None


class CreateSessionRequest(BaseModel):
    workspace_id: str
    mode: str
    input_asset_ids: list[str] = Field(default_factory=list)
    primary_input_asset_id: str
    companion_asset_ids: list[str] = Field(default_factory=list)
    output_policy: SessionOutputPolicyRequest = Field(default_factory=SessionOutputPolicyRequest)


class SessionResponse(BaseModel):
    session_id: str
    workspace_id: str
    mode: str
    input_asset_ids: list[str] = Field(default_factory=list)
    primary_input_asset_id: str
    companion_asset_ids: list[str] = Field(default_factory=list)
    resolved_output_dir: str
    resolved_temp_dir: str
    status: str
    validation: dict = Field(default_factory=dict)
