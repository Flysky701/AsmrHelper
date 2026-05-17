"""Pydantic schemas for task endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    detail: str = ""


class TaskListResponse(BaseModel):
    tasks: list[TaskStatusResponse]
