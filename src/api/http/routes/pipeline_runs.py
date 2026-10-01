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
    TaskStatusResponse,
)
from src.app.services import PipelineTaskOrchestrator

router = APIRouter(prefix="/pipeline-runs", tags=["pipeline-runs"])


def _to_v1_pipeline_request(body: PipelineRunCreateRequest) -> PipelineRequest:
    profile = body.execution_profile.model_dump(exclude_none=body.execution_profile.version == 2)
    if profile.get("version") == 1 and profile.get("workflow") is None:
        profile.pop("workflow", None)
    return PipelineRequest(
        input_path=body.input.path,
        output_dir=body.output.directory,
        source_lang=getattr(body.execution_profile, "source_lang", "ja"),
        target_lang=getattr(body.execution_profile, "target_lang", "zh"),
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
