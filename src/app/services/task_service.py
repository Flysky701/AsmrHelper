"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading
from datetime import datetime, UTC

from ..dto import TaskSpec, TaskStatus
from ..errors import AppValidationError


class TaskService:
    """Track application tasks in memory for the current process."""

    _TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "skipped"})

    def __init__(self, max_concurrent: int = 4) -> None:
        self._tasks: dict[str, TaskStatus] = {}
        self._task_specs: dict[str, TaskSpec] = {}
        self._counters: dict[str, int] = {}
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()

    def create_task(self, kind: str) -> TaskStatus:
        with self._lock:
            next_id = self._counters.get(kind, 0) + 1
            self._counters[kind] = next_id
            task = TaskStatus(task_id=f"{kind}-{next_id}", state="pending")
            self._tasks[task.task_id] = task
            return self._clone_task(task)

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
            next_id = self._counters.get(task_type, 0) + 1
            self._counters[task_type] = next_id
            task_id = f"{task_type}-{next_id}"
            task_spec = TaskSpec(
                task_id=task_id,
                task_type=task_type,
                task_source=task_source,
                session_id=session_id,
                input_asset_id=input_asset_id,
                companion_asset_ids=list(companion_asset_ids or []),
                execution_profile=dict(execution_profile or {}),
                priority=priority,
                dedupe_key=dedupe_key,
                created_at=datetime.now(UTC).isoformat(),
            )
            task_status = TaskStatus(
                task_id=task_id,
                state="pending",
                task_type=task_type,
                task_source=task_source,
                session_id=session_id,
            )
            self._task_specs[task_id] = task_spec
            self._tasks[task_id] = task_status
            return self._clone_spec(task_spec), self._clone_task(task_status)

    def get_task(self, task_id: str) -> TaskStatus:
        with self._lock:
            try:
                task = self._tasks[task_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown task id: {task_id}") from exc
            return self._clone_task(task)

    def get_task_spec(self, task_id: str) -> TaskSpec:
        with self._lock:
            try:
                task_spec = self._task_specs[task_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown task id: {task_id}") from exc
            return self._clone_spec(task_spec)

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

    def skip_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._update_task(
            task_id,
            state="skipped",
            progress=1.0,
            message=message,
            detail=detail,
        )

    def cancel_task(self, task_id: str, message: str = "cancelled by user") -> TaskStatus:
        with self._lock:
            current = self._tasks.get(task_id)
            if current is None:
                raise AppValidationError(f"unknown task id: {task_id}")
            if current.state in self._TERMINAL_STATES:
                raise AppValidationError(f"cannot cancel task in state: {current.state}")
        return self._update_task(
            task_id,
            state="cancelled",
            message=message,
        )

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.state == "running")

    def can_start(self) -> bool:
        return self.running_count() < self._max_concurrent

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
                task_type=current.task_type,
                task_source=current.task_source,
                session_id=current.session_id,
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
            task_type=task.task_type,
            task_source=task.task_source,
            session_id=task.session_id,
        )

    @staticmethod
    def _clone_spec(task_spec: TaskSpec) -> TaskSpec:
        return TaskSpec(
            task_id=task_spec.task_id,
            task_type=task_spec.task_type,
            task_source=task_spec.task_source,
            session_id=task_spec.session_id,
            input_asset_id=task_spec.input_asset_id,
            companion_asset_ids=list(task_spec.companion_asset_ids),
            execution_profile=dict(task_spec.execution_profile),
            priority=task_spec.priority,
            dedupe_key=task_spec.dedupe_key,
            created_at=task_spec.created_at,
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
