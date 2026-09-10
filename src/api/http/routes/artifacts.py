"""Artifact routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.api.http.dependencies import artifact_service
from src.api.http.schemas.artifacts import (
    ArtifactResponse,
)
from src.app.services import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _to_record_response(record) -> ArtifactResponse:
    return ArtifactResponse.from_record(
        record,
        primary_artifact_id=record.artifact_id if record.is_primary else None,
    )


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    svc: ArtifactService = Depends(artifact_service),
):
    record = svc.get_artifact(artifact_id)
    return _to_record_response(record)


@router.get("/{artifact_id}/file")
def download_artifact_file(
    artifact_id: str,
    svc: ArtifactService = Depends(artifact_service),
):
    record = svc.get_artifact(artifact_id)
    file_path = Path(record.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"artifact file not found: {record.path}")
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )
