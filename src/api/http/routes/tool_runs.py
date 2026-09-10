"""Task-driven tool run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tool_registry
from src.api.http.schemas.tasks import (
    TaskStatusResponse,
)
from src.api.http.schemas.tool_runs import (
    ToolDescriptorResponse,
    ToolListResponse,
    ToolTaskCreateRequest,
)
from src.app.services import ToolRegistry

router = APIRouter(tags=["tool-runs"])


@router.get("/tools", response_model=ToolListResponse)
def list_tool_tasks(
    svc: ToolRegistry = Depends(tool_registry),
):
    return ToolListResponse(
        tools=[ToolDescriptorResponse(**tool) for tool in svc.list_tools()]
    )


@router.post("/tool-runs", response_model=TaskStatusResponse, status_code=201)
def create_tool_task(
    body: ToolTaskCreateRequest,
    svc: ToolRegistry = Depends(tool_registry),
):
    task = svc.create_task(
        task_type=body.task_type,
        input_path=body.input_path,
        companion_paths=body.companion_paths,
        execution_profile=body.execution_profile,
    )
    return TaskStatusResponse.from_task_status(task)
