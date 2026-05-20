"""Schemas for workspace endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class WorkspaceResolveResponse(BaseModel):
    workspace_id: str
    workspace_root: str
    default_output_root: str
    default_temp_root: str
    default_models_root: str
