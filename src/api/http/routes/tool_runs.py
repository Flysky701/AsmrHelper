"""Task-driven tool run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tool_registry
from src.api.http.schemas.tasks import (
    ArtifactRecordResponse,
    TaskArtifactsResponse,
    TaskResultResponse,
    TaskStatusResponse,
)
from src.api.http.schemas.tool_runs import (
    ToolDescriptorResponse,
    ToolListResponse,
    ToolTaskRunRequest,
    ToolTaskRunResponse,
)
from src.app.services import ToolRegistry

router = APIRouter(prefix="/tool-runs", tags=["tool-runs"])


@router.get("", response_model=ToolListResponse)
def list_tool_tasks(
    svc: ToolRegistry = Depends(tool_registry),
):
    return ToolListResponse(
        tools=[ToolDescriptorResponse(**tool) for tool in svc.list_tools()]
    )


@router.post("", response_model=ToolTaskRunResponse)
def run_tool_task(
    body: ToolTaskRunRequest,
    svc: ToolRegistry = Depends(tool_registry),
):
    result = svc.run_task(body.task_id)
    return ToolTaskRunResponse(
        task=TaskStatusResponse.from_task_status(result["task"]),
        tool_name=result["tool_name"],
        summary=dict(result["summary"]),
    )


@router.get("/{task_id}", response_model=TaskResultResponse)
def get_tool_run(
    task_id: str,
    svc: ToolRegistry = Depends(tool_registry),
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
def get_tool_run_artifacts(
    task_id: str,
    svc: ToolRegistry = Depends(tool_registry),
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
