"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading
from src.core.tasks import TaskRegistry, TaskSpec, TaskStatus
from ..errors import AppValidationError


class TaskService:
    """Track application tasks in memory for the current process."""

    def __init__(self, max_concurrent: int = 4) -> None:
        self._registry = TaskRegistry(max_concurrent=max_concurrent)
        self._lock = threading.Lock()

    def create_task_spec(
        self,
        *,
        task_type: str,
        task_source: str,
        session_id: str,
        input_asset_id: str = "",
        companion_asset_ids: list[str] | None = None,
        execution_profile: dict | None = None,
        priority: int = 0,
        dedupe_key: str = "",
    ) -> tuple[TaskSpec, TaskStatus]:
        with self._lock:
            try:
                return self._registry.create_task_spec(
                    task_type=task_type,
                    task_source=task_source,
                    session_id=session_id,
                    input_asset_id=input_asset_id,
                    companion_asset_ids=companion_asset_ids,
                    execution_profile=execution_profile,
                    priority=priority,
                    dedupe_key=dedupe_key,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_task(self, task_id: str) -> TaskStatus:
        with self._lock:
            try:
                return self._registry.get_task(task_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_task_spec(self, task_id: str) -> TaskSpec:
        with self._lock:
            try:
                return self._registry.get_task_spec(task_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def start_task(self, task_id: str, message: str = "") -> TaskStatus:
        return self._guard(lambda: self._registry.start_task(task_id, message=message))

    def update_progress(self, task_id: str, progress: float, message: str = "") -> TaskStatus:
        return self._guard(lambda: self._registry.update_progress(task_id, progress, message=message))

    def complete_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._guard(lambda: self._registry.complete_task(task_id, message=message, detail=detail))

    def fail_task(self, task_id: str, message: str, detail: str = "") -> TaskStatus:
        return self._guard(lambda: self._registry.fail_task(task_id, message=message, detail=detail))

    def skip_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._guard(lambda: self._registry.skip_task(task_id, message=message, detail=detail))

    def cancel_task(self, task_id: str, message: str = "cancelled by user") -> TaskStatus:
        return self._guard(lambda: self._registry.cancel_task(task_id, message=message))

    def retry_task(self, task_id: str, message: str = "queued for retry") -> TaskStatus:
        return self._guard(lambda: self._registry.retry_task(task_id, message=message))

    def set_review_state(self, task_id: str, review_state: str) -> TaskStatus:
        return self._guard(lambda: self._registry.set_review_state(task_id, review_state))

    def set_review_note(self, task_id: str, review_note: str) -> TaskStatus:
        return self._guard(lambda: self._registry.set_review_note(task_id, review_note))

    def running_count(self) -> int:
        with self._lock:
            return self._registry.running_count()

    def can_start(self) -> bool:
        with self._lock:
            return self._registry.can_start()

    def list_tasks(self, *, state: str | None = None) -> list[TaskStatus]:
        with self._lock:
            return self._registry.list_tasks(state=state)

    def get_queue_snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._registry.get_queue_snapshot()

    @staticmethod
    def _guard(fn):
        try:
            return fn()
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc


_service: TaskService | None = None
_lock = threading.Lock()


def get_task_service() -> TaskService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TaskService()
    return _service
