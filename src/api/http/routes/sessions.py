"""Processing session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import session_service
from src.api.http.schemas.sessions import CreateSessionRequest, SessionResponse
from src.app.services import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
def create_session(
    body: CreateSessionRequest,
    svc: SessionService = Depends(session_service),
):
    session = svc.create_session(
        workspace_id=body.workspace_id,
        mode=body.mode,
        input_asset_ids=body.input_asset_ids,
        primary_input_asset_id=body.primary_input_asset_id,
        companion_asset_ids=body.companion_asset_ids,
        output_policy=body.output_policy.model_dump(),
    )
    return SessionResponse(
        session_id=session.session_id,
        workspace_id=session.workspace_id,
        mode=session.mode,
        input_asset_ids=session.input_asset_ids,
        primary_input_asset_id=session.primary_input_asset_id,
        companion_asset_ids=session.companion_asset_ids,
        resolved_output_dir=session.resolved_output_dir,
        resolved_temp_dir=session.resolved_temp_dir,
        status=session.status,
        validation=session.validation,
    )
