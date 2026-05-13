"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading

from ..dto import TaskStatus
from ..errors import AppValidationError


class TaskService:
    """Track application tasks in memory for the current process."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskStatus] = {}
        self._counters: dict[str, int] = {}

    def create_task(self, kind: str) -> TaskStatus:
        next_id = self._counters.get(kind, 0) + 1
        self._counters[kind] = next_id
        task = TaskStatus(task_id=f"{kind}-{next_id}", state="pending")
        self._tasks[task.task_id] = task
        return task

    def get_task(self, task_id: str) -> TaskStatus:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise AppValidationError(f"unknown task id: {task_id}") from exc

    def start(self, task_id: str, message: str = "") -> TaskStatus:
        return self._update_task(task_id, state="running", message=message)

    def update_progress(self, task_id: str, progress: float, message: str = "") -> TaskStatus:
        return self._update_task(task_id, progress=progress, message=message)

    def complete(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._update_task(
            task_id,
            state="completed",
            progress=1.0,
            message=message,
            detail=detail,
        )

    def fail(self, task_id: str, message: str, detail: str = "") -> TaskStatus:
        return self._update_task(
            task_id,
            state="failed",
            progress=1.0,
            message=message,
            detail=detail,
        )

    def _update_task(
        self,
        task_id: str,
        *,
        state: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        detail: str | None = None,
    ) -> TaskStatus:
        current = self.get_task(task_id)
        updated = TaskStatus(
            task_id=current.task_id,
            state=state if state is not None else current.state,
            progress=progress if progress is not None else current.progress,
            message=message if message is not None else current.message,
            detail=detail if detail is not None else current.detail,
        )
        self._tasks[task_id] = updated
        return updated


_service: TaskService | None = None
_lock = threading.Lock()


def get_task_service() -> TaskService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TaskService()
    return _service
