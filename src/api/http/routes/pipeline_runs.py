"""Task-driven pipeline run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import pipeline_task_orchestrator
from src.api.http.routes.pipeline import _build_task_response, _to_pipeline_request
from src.api.http.schemas.pipeline import PipelineRunRequest
from src.api.http.schemas.pipeline import ArtifactSetResponse
from src.api.http.schemas.pipeline_runs import (
    PipelineRunAcceptedResponse,
    PipelineRunCreateRequest,
    PipelineTaskRunRequest,
    PipelineTaskRunResponse,
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


@router.post("/start", response_model=TaskStatusResponse)
def start_pipeline_task(
    body: PipelineTaskRunRequest,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    task = svc.start_task(body.task_id)
    return TaskStatusResponse.from_task_status(task)


@router.post("", response_model=PipelineRunAcceptedResponse, status_code=202)
def submit_pipeline_run(
    body: PipelineRunCreateRequest | PipelineRunRequest,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    request = (
        _to_v1_pipeline_request(body)
        if isinstance(body, PipelineRunCreateRequest)
        else _to_pipeline_request(body)
    )
    task = svc.submit_task(request)
    return PipelineRunAcceptedResponse(
        task=TaskStatusResponse.from_task_status(task),
    )


@router.post("/execute", response_model=PipelineTaskRunResponse)
def execute_pipeline_task(
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
    return TaskResultResponse.from_view(svc.get_task_result(task.task_id))


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
def get_pipeline_run_artifacts(
    task_id: str,
    svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
):
    return TaskArtifactsResponse.from_view(svc.get_task_result(task_id))
