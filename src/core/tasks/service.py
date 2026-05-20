"""Core in-memory task registry and lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

from .models import TaskSpec, TaskStatus


class TaskRegistry:
    """Track task specs and runtime state for the current process."""

    TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "skipped"})
    VALID_REVIEW_STATES = frozenset({"", "accepted", "needs_review", "needs_rework"})

    def __init__(self, max_concurrent: int = 4) -> None:
        self._tasks: dict[str, TaskStatus] = {}
        self._task_specs: dict[str, TaskSpec] = {}
        self._counters: dict[str, int] = {}
        self._max_concurrent = max_concurrent

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
        return self.clone_spec(task_spec), self.clone_task(task_status)

    def get_task(self, task_id: str) -> TaskStatus:
        try:
            task = self._tasks[task_id]
        except KeyError as exc:
            raise ValueError(f"unknown task id: {task_id}") from exc
        return self.clone_task(task)

    def get_task_spec(self, task_id: str) -> TaskSpec:
        try:
            task_spec = self._task_specs[task_id]
        except KeyError as exc:
            raise ValueError(f"unknown task id: {task_id}") from exc
        return self.clone_spec(task_spec)

    def start_task(self, task_id: str, message: str = "") -> TaskStatus:
        return self.update_task(task_id, state="running", message=message)

    def update_progress(self, task_id: str, progress: float, message: str = "") -> TaskStatus:
        return self.update_task(task_id, progress=progress, message=message)

    def complete_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self.update_task(task_id, state="completed", progress=1.0, message=message, detail=detail)

    def fail_task(self, task_id: str, message: str, detail: str = "") -> TaskStatus:
        return self.update_task(task_id, state="failed", progress=1.0, message=message, detail=detail)

    def skip_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self.update_task(task_id, state="skipped", progress=1.0, message=message, detail=detail)

    def cancel_task(self, task_id: str, message: str = "cancelled by user") -> TaskStatus:
        current = self.get_task(task_id)
        if current.state in self.TERMINAL_STATES:
            raise ValueError(f"cannot cancel task in state: {current.state}")
        return self.update_task(task_id, state="cancelled", message=message)

    def retry_task(self, task_id: str, message: str = "queued for retry") -> TaskStatus:
        current = self.get_task(task_id)
        if current.state not in {"failed", "cancelled"}:
            raise ValueError(f"cannot retry task in state: {current.state}")
        return self.update_task(
            task_id,
            state="pending",
            progress=0.0,
            message=message,
            detail="",
            review_state="",
            review_note="",
        )

    def set_review_state(self, task_id: str, review_state: str) -> TaskStatus:
        if review_state not in self.VALID_REVIEW_STATES:
            raise ValueError(
                f"invalid review_state: {review_state!r}, "
                f"expected one of: {', '.join(sorted(self.VALID_REVIEW_STATES - {''}))}"
            )
        current = self.get_task(task_id)
        if current.state not in self.TERMINAL_STATES:
            raise ValueError(f"cannot set review_state on task in state: {current.state}")
        return self.update_task(task_id, review_state=review_state)

    def set_review_note(self, task_id: str, review_note: str) -> TaskStatus:
        current = self.get_task(task_id)
        if current.state not in self.TERMINAL_STATES:
            raise ValueError(f"cannot set review_note on task in state: {current.state}")
        return self.update_task(task_id, review_note=review_note)

    def list_tasks(self, *, state: str | None = None) -> list[TaskStatus]:
        tasks = self._tasks.values()
        if state is not None:
            tasks = [task for task in tasks if task.state == state]
        return [self.clone_task(task) for task in tasks]

    def running_count(self) -> int:
        return sum(1 for task in self._tasks.values() if task.state == "running")

    def can_start(self) -> bool:
        return self.running_count() < self._max_concurrent

    def get_queue_snapshot(self) -> dict[str, object]:
        grouped: dict[str, list[TaskStatus]] = {
            "pending": [],
            "running": [],
            "completed": [],
            "failed": [],
            "cancelled": [],
            "skipped": [],
        }
        for task in self._tasks.values():
            grouped.setdefault(task.state, []).append(self.clone_task(task))
        return {
            "queued_tasks": grouped["pending"],
            "running_tasks": grouped["running"],
            "completed_tasks": grouped["completed"],
            "failed_tasks": grouped["failed"],
            "cancelled_tasks": grouped["cancelled"],
            "skipped_tasks": grouped["skipped"],
            "queue_stats": {
                "pending": len(grouped["pending"]),
                "running": len(grouped["running"]),
                "completed": len(grouped["completed"]),
                "failed": len(grouped["failed"]),
                "cancelled": len(grouped["cancelled"]),
                "skipped": len(grouped["skipped"]),
                "max_concurrent": self._max_concurrent,
                "can_start": self.can_start(),
            },
        }

    def update_task(
        self,
        task_id: str,
        *,
        state: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        detail: str | None = None,
        review_state: str | None = None,
        review_note: str | None = None,
    ) -> TaskStatus:
        try:
            current = self._tasks[task_id]
        except KeyError as exc:
            raise ValueError(f"unknown task id: {task_id}") from exc

        updated = TaskStatus(
            task_id=current.task_id,
            state=state if state is not None else current.state,
            progress=progress if progress is not None else current.progress,
            message=message if message is not None else current.message,
            detail=detail if detail is not None else current.detail,
            task_type=current.task_type,
            task_source=current.task_source,
            session_id=current.session_id,
            review_state=review_state if review_state is not None else current.review_state,
            review_note=review_note if review_note is not None else current.review_note,
        )
        self._tasks[task_id] = updated
        return self.clone_task(updated)

    @staticmethod
    def clone_task(task: TaskStatus) -> TaskStatus:
        return TaskStatus(
            task_id=task.task_id,
            state=task.state,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
            task_type=task.task_type,
            task_source=task.task_source,
            session_id=task.session_id,
            review_state=task.review_state,
            review_note=task.review_note,
        )

    @staticmethod
    def clone_spec(task_spec: TaskSpec) -> TaskSpec:
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
