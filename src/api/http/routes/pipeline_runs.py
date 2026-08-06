"""Task-driven pipeline run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import pipeline_task_orchestrator
from src.api.http.schemas.pipeline_runs import (
    PipelineRunAcceptedResponse,
    PipelineRunCreateRequest,
)
from src.app.dto import PipelineRequest
from src.api.http.schemas.tasks import (
    TaskArtifactsResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from src.app.services import PipelineTaskOrchestrator

router = APIRouter(prefix="/pipeline-runs", tags=["pipeline-runs"])


def _to_v1_pipeline_request(body: PipelineRunCreateRequest) -> PipelineRequest:
    profile = body.execution_profile.model_dump()
    return PipelineRequest(
        input_path=body.input.path,
        output_dir=body.output.directory,
        source_lang=body.execution_profile.source_lang,
        target_lang=body.execution_profile.target_lang,
        companion_paths=list(body.input.companion_paths),
        execution_profile=profile,
    )


@router.post("", response_model=PipelineRunAcceptedResponse, status_code=202)
def submit_pipeline_run(
    body: PipelineRunCreateRequest,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    task = svc.submit_task(_to_v1_pipeline_request(body))
    return PipelineRunAcceptedResponse(
        task=TaskStatusResponse.from_task_status(task),
    )


@router.get("/{task_id}", response_model=TaskResultResponse)
def get_pipeline_run(
    task_id: str,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    task = svc.get_task(task_id)
    return TaskResultResponse.from_view(svc.get_task_result(task.task_id))


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
def get_pipeline_run_artifacts(
    task_id: str,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    return TaskArtifactsResponse.from_view(svc.get_task_result(task_id))
