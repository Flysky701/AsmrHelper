"""Task-driven pipeline run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import pipeline_task_orchestrator
from src.api.http.routes.pipeline import _build_task_response
from src.api.http.schemas.pipeline import ArtifactSetResponse
from src.api.http.schemas.pipeline_runs import PipelineTaskRunRequest, PipelineTaskRunResponse
from src.api.http.schemas.tasks import (
    ArtifactRecordResponse,
    TaskArtifactsResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from src.app.services import PipelineTaskOrchestrator

router = APIRouter(prefix="/pipeline-runs", tags=["pipeline-runs"])


@router.post("", response_model=PipelineTaskRunResponse)
def run_pipeline_task(
    body: PipelineTaskRunRequest,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    result = svc.run_task(body.task_id)
    task = _build_task_response(result)
    return PipelineTaskRunResponse(
        success=result.success,
        input_path=result.input_path,
        task=task,
        task_id=result.task_id,
        task_state=result.task_state,
        artifacts=ArtifactSetResponse(
            files=result.artifacts.files,
            primary_output=result.artifacts.primary_output,
        ),
        mix_path=result.mix_path,
        exported_subtitle=result.exported_subtitle,
        total_duration=result.total_duration,
        error_message=result.error_message,
    )


@router.get("/{task_id}", response_model=TaskResultResponse)
def get_pipeline_run(
    task_id: str,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    task = svc.get_task(task_id)
    result_view = svc.get_task_result(task_id)
    primary_output = result_view["primary_output"]
    secondary_outputs = result_view["secondary_outputs"]
    return TaskResultResponse(
        task=TaskStatusResponse.from_task_status(task),
        primary_output=(
            ArtifactRecordResponse(
                artifact_id=primary_output.artifact_id,
                task_id=primary_output.task_id,
                artifact_type=primary_output.artifact_type,
                path=primary_output.path,
                label=primary_output.label,
                preview_kind=primary_output.preview_kind,
                stage=primary_output.stage,
                is_primary=primary_output.is_primary,
                metadata=dict(primary_output.metadata),
            )
            if primary_output is not None
            else None
        ),
        secondary_outputs=[
            ArtifactRecordResponse(
                artifact_id=entry.artifact_id,
                task_id=entry.task_id,
                artifact_type=entry.artifact_type,
                path=entry.path,
                label=entry.label,
                preview_kind=entry.preview_kind,
                stage=entry.stage,
                is_primary=entry.is_primary,
                metadata=dict(entry.metadata),
            )
            for entry in secondary_outputs
        ],
        warnings=list(result_view["warnings"]),
    )


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
def get_pipeline_run_artifacts(
    task_id: str,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    artifacts = svc.get_task_artifacts(task_id)
    return TaskArtifactsResponse(
        task_id=task_id,
        files=dict(artifacts.files),
        primary_output=artifacts.primary_output,
        entries=[
            ArtifactRecordResponse(
                artifact_id=entry.artifact_id,
                task_id=entry.task_id,
                artifact_type=entry.artifact_type,
                path=entry.path,
                label=entry.label,
                preview_kind=entry.preview_kind,
                stage=entry.stage,
                is_primary=entry.is_primary,
                metadata=dict(entry.metadata),
            )
            for entry in artifacts.entries
        ],
    )
