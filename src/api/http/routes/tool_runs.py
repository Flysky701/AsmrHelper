"""Task-driven tool run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tool_registry
from src.api.http.schemas.tasks import (
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
    return TaskResultResponse.from_view(svc.get_task_result(task.task_id))


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
def get_tool_run_artifacts(
    task_id: str,
    svc: ToolRegistry = Depends(tool_registry),
):
    return TaskArtifactsResponse.from_view(svc.get_task_result(task_id))
