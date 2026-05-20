"""Artifact routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from src.api.http.dependencies import artifact_service
from src.api.http.schemas.artifacts import (
    ArtifactRecordResponse,
    ArtifactSetResponse,
    TaskResultViewResponse,
)
from src.app.services import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _to_record_response(record) -> ArtifactRecordResponse:
    return ArtifactRecordResponse(
        artifact_id=record.artifact_id,
        task_id=record.task_id,
        artifact_type=record.artifact_type,
        path=record.path,
        label=record.label,
        preview_kind=record.preview_kind,
        stage=record.stage,
        is_primary=record.is_primary,
        metadata=dict(record.metadata),
    )


@router.get("/{task_id}", response_model=ArtifactSetResponse)
def get_task_artifacts(
    task_id: str,
    svc: ArtifactService = Depends(artifact_service),
):
    artifact_set = svc.get_task_artifacts(task_id)
    return ArtifactSetResponse(
        task_id=task_id,
        files=dict(artifact_set.files),
        primary_output=artifact_set.primary_output,
        entries=[_to_record_response(e) for e in artifact_set.entries],
    )


@router.get("/{task_id}/result", response_model=TaskResultViewResponse)
def get_task_result_view(
    task_id: str,
    svc: ArtifactService = Depends(artifact_service),
):
    result = svc.get_task_result_view(task_id)
    primary = result["primary_output"]
    return TaskResultViewResponse(
        task_id=task_id,
        primary_output=_to_record_response(primary) if primary else None,
        secondary_outputs=[_to_record_response(e) for e in result["secondary_outputs"]],
        warnings=list(result["warnings"]),
    )


@router.get("/detail/{artifact_id}", response_model=ArtifactRecordResponse)
def get_artifact(
    artifact_id: str,
    svc: ArtifactService = Depends(artifact_service),
):
    record = svc.get_artifact(artifact_id)
    return _to_record_response(record)


@router.get("/detail/{artifact_id}/file")
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
