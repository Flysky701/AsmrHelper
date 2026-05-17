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
        self._lock = threading.Lock()

    def create_task(self, kind: str) -> TaskStatus:
        with self._lock:
            next_id = self._counters.get(kind, 0) + 1
            self._counters[kind] = next_id
            task = TaskStatus(task_id=f"{kind}-{next_id}", state="pending")
            self._tasks[task.task_id] = task
            return self._clone_task(task)

    def get_task(self, task_id: str) -> TaskStatus:
        with self._lock:
            try:
                task = self._tasks[task_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown task id: {task_id}") from exc
            return self._clone_task(task)

    def start_task(self, task_id: str, message: str = "") -> TaskStatus:
        return self._update_task(task_id, state="running", message=message)

    def update_progress(self, task_id: str, progress: float, message: str = "") -> TaskStatus:
        return self._update_task(task_id, progress=progress, message=message)

    def complete_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._update_task(
            task_id,
            state="completed",
            progress=1.0,
            message=message,
            detail=detail,
        )

    def fail_task(self, task_id: str, message: str, detail: str = "") -> TaskStatus:
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
        with self._lock:
            try:
                current = self._tasks[task_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown task id: {task_id}") from exc

            updated = TaskStatus(
                task_id=current.task_id,
                state=state if state is not None else current.state,
                progress=progress if progress is not None else current.progress,
                message=message if message is not None else current.message,
                detail=detail if detail is not None else current.detail,
            )
            self._tasks[task_id] = updated
            return self._clone_task(updated)

    def list_tasks(self) -> list[TaskStatus]:
        with self._lock:
            return [self._clone_task(t) for t in self._tasks.values()]

    @staticmethod
    def _clone_task(task: TaskStatus) -> TaskStatus:
        return TaskStatus(
            task_id=task.task_id,
            state=task.state,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
        )


_service: TaskService | None = None
_lock = threading.Lock()


def get_task_service() -> TaskService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TaskService()
    return _service
