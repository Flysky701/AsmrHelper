"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading
from src.core.tasks import RuntimeEvent, TaskRegistry, TaskSpec, TaskStatus
from ..errors import AppValidationError
from ..persistence import SqliteStateStore, get_state_store


class TaskService:
    """Track application tasks in memory for the current process."""

    def __init__(
        self,
        max_concurrent: int = 4,
        state_store: SqliteStateStore | None = None,
    ) -> None:
        self._registry = TaskRegistry(max_concurrent=max_concurrent)
        self._lock = threading.Lock()
        self._state_store = state_store
        self._restored_task_ids: set[str] = set()
        if self._state_store is not None:
            self._state_store.purge_unfinished()
            for task_spec, task_status in self._state_store.load_terminal_tasks():
                self._registry.restore_task(task_spec, task_status)
                self._restored_task_ids.add(task_status.task_id)

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
                result = self._registry.create_task_spec(
                    task_type=task_type,
                    task_source=task_source,
                    session_id=session_id,
                    input_asset_id=input_asset_id,
                    companion_asset_ids=companion_asset_ids,
                    execution_profile=execution_profile,
                    priority=priority,
                    dedupe_key=dedupe_key,
                )
                if self._state_store is not None:
                    self._state_store.save_task(*result)
                return result
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

    def start_task(
        self, task_id: str, message: str = "", *, stage: str | None = "prepare"
    ) -> TaskStatus:
        return self._guard(
            lambda: self._registry.start_task(task_id, message=message, stage=stage)
        )

    def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str = "",
        *,
        stage: str | None = None,
        detail: str | None = None,
    ) -> TaskStatus:
        return self._guard(
            lambda: self._registry.update_progress(
                task_id,
                progress,
                message=message,
                stage=stage,
                detail=detail,
            )
        )

    def complete_task(
        self,
        task_id: str,
        message: str = "",
        detail: str = "",
        *,
        stage: str | None = None,
        artifact_set_id: str | None = None,
    ) -> TaskStatus:
        return self._guard(
            lambda: self._registry.complete_task(
                task_id,
                message=message,
                detail=detail,
                stage=stage,
                artifact_set_id=artifact_set_id,
            )
        )

    def fail_task(
        self,
        task_id: str,
        message: str,
        detail: str = "",
        *,
        stage: str | None = None,
        error: dict[str, object] | None = None,
    ) -> TaskStatus:
        return self._guard(
            lambda: self._registry.fail_task(
                task_id,
                message=message,
                detail=detail,
                stage=stage,
                error=error,
            )
        )

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

    def _guard(self, fn):
        with self._lock:
            try:
                result = fn()
                if self._state_store is not None:
                    task_spec = self._registry.get_task_spec(result.task_id)
                    self._state_store.save_task(task_spec, result)
                return result
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[RuntimeEvent]:
        with self._lock:
            try:
                return self._registry.list_events(
                    task_id,
                    after_sequence=after_sequence,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def is_restored_history(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._restored_task_ids


_service: TaskService | None = None
_lock = threading.Lock()


def get_task_service() -> TaskService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TaskService(state_store=get_state_store())
    return _service
