"""Task routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import task_service
from src.api.http.schemas.tasks import TaskListResponse, TaskStatusResponse
from src.app.services import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse)
def list_tasks(
    svc: TaskService = Depends(task_service),
):
    tasks = svc.list_tasks()
    return TaskListResponse(
        tasks=[
            TaskStatusResponse(
                task_id=t.task_id,
                state=t.state,
                progress=t.progress,
                message=t.message,
                detail=t.detail,
            )
            for t in tasks
        ]
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    task = svc.get_task(task_id)
    return TaskStatusResponse(
        task_id=task.task_id,
        state=task.state,
        progress=task.progress,
        message=task.message,
        detail=task.detail,
    )
