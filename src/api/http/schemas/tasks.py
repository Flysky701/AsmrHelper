"""Pydantic schemas for task endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.app.dto import TaskStatus


TaskState = Literal["pending", "running", "completed", "failed"]


class TaskStatusResponse(BaseModel):
    task_id: str
    state: TaskState
    progress: float = Field(0.0, ge=0.0, le=1.0)
    message: str = ""
    detail: str = ""

    @classmethod
    def from_task_status(cls, task: TaskStatus) -> "TaskStatusResponse":
        return cls(
            task_id=task.task_id,
            state=task.state,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
        )


class TaskListResponse(BaseModel):
    tasks: list[TaskStatusResponse]

    @classmethod
    def from_tasks(cls, tasks: list[TaskStatus]) -> "TaskListResponse":
        return cls(tasks=[TaskStatusResponse.from_task_status(task) for task in tasks])
