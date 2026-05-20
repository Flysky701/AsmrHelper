"""Workspace routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import workspace_service
from src.api.http.schemas.workspaces import WorkspaceResolveResponse
from src.app.services import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/resolve", response_model=WorkspaceResolveResponse)
def resolve_workspace(
    svc: WorkspaceService = Depends(workspace_service),
):
    workspace = svc.resolve()
    return WorkspaceResolveResponse(
        workspace_id=workspace.workspace_id,
        workspace_root=workspace.workspace_root,
        default_output_root=workspace.default_output_root,
        default_temp_root=workspace.default_temp_root,
        default_models_root=workspace.default_models_root,
    )
