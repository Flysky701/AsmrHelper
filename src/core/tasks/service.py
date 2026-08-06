"""Core in-memory task registry and lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

from .executors import ExecutorRegistry, build_default_executor_registry
from .models import RuntimeEvent, TaskSpec, TaskStatus


class TaskRegistry:
    """Track task specs and runtime state for the current process."""

    TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "skipped"})
    VALID_REVIEW_STATES = frozenset({"", "accepted", "needs_review", "needs_rework"})

    def __init__(
        self,
        max_concurrent: int = 4,
        executor_registry: ExecutorRegistry | None = None,
    ) -> None:
        self._tasks: dict[str, TaskStatus] = {}
        self._task_specs: dict[str, TaskSpec] = {}
        self._events: dict[str, list[RuntimeEvent]] = {}
        self._event_sequences: dict[str, int] = {}
        self._counters: dict[str, int] = {}
        self._max_concurrent = max_concurrent
        self._executor_registry = executor_registry or build_default_executor_registry()

    @property
    def executor_registry(self) -> ExecutorRegistry:
        return self._executor_registry

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
        retry_of_task_id: str | None = None,
    ) -> tuple[TaskSpec, TaskStatus]:
        if not self._executor_registry.is_registered(task_type):
            raise ValueError(f"no executor registered for task_type: {task_type}")
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
            retry_of_task_id=retry_of_task_id,
            created_at=datetime.now(UTC).isoformat(),
        )
        task_status = TaskStatus(
            task_id=task_id,
            state="pending",
            task_type=task_type,
            task_source=task_source,
            session_id=session_id,
            input_asset_id=input_asset_id,
            created_at=task_spec.created_at,
            queued_at=task_spec.created_at,
            updated_at=task_spec.created_at,
            retry_of_task_id=retry_of_task_id,
        )
        self._task_specs[task_id] = task_spec
        self._tasks[task_id] = task_status
        self._events[task_id] = []
        self._event_sequences[task_id] = 0
        self._append_status_event(None, task_status)
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

    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[RuntimeEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if task_id not in self._tasks:
            raise ValueError(f"unknown task id: {task_id}")
        return [
            self.clone_event(event)
            for event in self._events.get(task_id, [])
            if event.sequence > after_sequence
        ]

    def restore_task(self, task_spec: TaskSpec, task_status: TaskStatus) -> None:
        if task_spec.task_id != task_status.task_id:
            raise ValueError("task spec and status IDs do not match")
        if task_status.state not in self.TERMINAL_STATES:
            raise ValueError("only terminal tasks can be restored")
        self._task_specs[task_spec.task_id] = self.clone_spec(task_spec)
        self._tasks[task_status.task_id] = self.clone_task(task_status)
        self._events[task_status.task_id] = []
        self._event_sequences[task_status.task_id] = 0
        self._append_event(
            task_status,
            event_type="task_restored",
            message="terminal task restored from history",
            data={"state": task_status.state, "historical": True},
        )

        prefix, separator, suffix = task_spec.task_id.rpartition("-")
        if separator and prefix == task_spec.task_type and suffix.isdigit():
            self._counters[task_spec.task_type] = max(
                self._counters.get(task_spec.task_type, 0),
                int(suffix),
            )

    def start_task(
        self,
        task_id: str,
        message: str = "",
        *,
        stage: str | None = "prepare",
    ) -> TaskStatus:
        current = self.get_task(task_id)
        if current.state == "running":
            # Starting is idempotent at the status boundary; TaskDispatcher
            # still guarantees that the executor callable runs only once.
            return current
        if current.state != "pending":
            raise ValueError(f"task can only be started once from pending: {current.state}")
        return self.update_task(task_id, state="running", message=message, stage=stage)

    def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str = "",
        *,
        stage: str | None = None,
        detail: str | None = None,
    ) -> TaskStatus:
        return self.update_task(
            task_id,
            progress=progress,
            message=message,
            stage=stage,
            detail=detail,
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
        return self.update_task(
            task_id,
            state="completed",
            progress=1.0,
            message=message,
            detail=detail,
            stage=stage,
            clear_error=True,
            artifact_set_id=artifact_set_id,
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
        current = self.get_task(task_id)
        resolved_stage = stage if stage is not None else current.stage
        resolved_error = error or {
            "code": "TASK_FAILED",
            "stage": resolved_stage,
            "message": message,
            "retryable": True,
            "detail": detail,
        }
        return self.update_task(
            task_id,
            state="failed",
            message=message,
            detail=detail,
            stage=resolved_stage,
            error=resolved_error,
        )

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
        previous_spec = self.get_task_spec(task_id)
        _, retried = self.create_task_spec(
            task_type=previous_spec.task_type,
            task_source=f"retry:{task_id}",
            session_id=previous_spec.session_id,
            input_asset_id=previous_spec.input_asset_id,
            companion_asset_ids=previous_spec.companion_asset_ids,
            execution_profile=previous_spec.execution_profile,
            priority=previous_spec.priority,
            dedupe_key="",
            retry_of_task_id=task_id,
        )
        if message:
            return self.update_task(retried.task_id, message=message)
        return retried

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
        stage: str | None = None,
        message: str | None = None,
        detail: str | None = None,
        error: dict[str, object] | None = None,
        artifact_set_id: str | None = None,
        queued_at: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        clear_error: bool = False,
        reset_runtime: bool = False,
        review_state: str | None = None,
        review_note: str | None = None,
    ) -> TaskStatus:
        try:
            current = self._tasks[task_id]
        except KeyError as exc:
            raise ValueError(f"unknown task id: {task_id}") from exc

        if progress is not None and not 0.0 <= progress <= 1.0:
            raise ValueError("task progress must be between 0.0 and 1.0")

        lifecycle_values = (
            state,
            progress,
            stage,
            message,
            detail,
            error,
            artifact_set_id,
            queued_at,
            started_at,
            finished_at,
            clear_error,
            reset_runtime,
        )
        if current.state in self.TERMINAL_STATES and any(
            value is not None and value is not False for value in lifecycle_values
        ):
            raise ValueError("terminal task is immutable")

        next_state = state if state is not None else current.state
        now = self._now()
        terminal = next_state in self.TERMINAL_STATES
        next_started_at = None if reset_runtime else started_at
        if next_started_at is None and not reset_runtime:
            next_started_at = current.started_at
            if next_state == "running" and next_started_at is None:
                next_started_at = now
        next_finished_at = None if reset_runtime else finished_at
        if next_finished_at is None and not reset_runtime:
            next_finished_at = current.finished_at
            if terminal and next_finished_at is None:
                next_finished_at = now

        updated = TaskStatus(
            task_id=current.task_id,
            state=next_state,
            stage=(
                None
                if reset_runtime
                else stage if stage is not None else current.stage
            ),
            progress=progress if progress is not None else current.progress,
            message=message if message is not None else current.message,
            detail=detail if detail is not None else current.detail,
            task_type=current.task_type,
            task_source=current.task_source,
            session_id=current.session_id,
            input_asset_id=current.input_asset_id,
            created_at=current.created_at,
            queued_at=queued_at if queued_at is not None else current.queued_at,
            started_at=next_started_at,
            updated_at=now,
            finished_at=next_finished_at,
            error=None if clear_error or reset_runtime else error if error is not None else current.error,
            artifact_set_id=(
                None
                if reset_runtime
                else artifact_set_id if artifact_set_id is not None else current.artifact_set_id
            ),
            retry_of_task_id=current.retry_of_task_id,
            review_state=review_state if review_state is not None else current.review_state,
            review_note=review_note if review_note is not None else current.review_note,
        )
        self._tasks[task_id] = updated
        self._append_status_event(current, updated)
        return self.clone_task(updated)

    def _append_status_event(
        self,
        previous: TaskStatus | None,
        current: TaskStatus,
    ) -> None:
        level = "info"
        if previous is None:
            event_type = "task_created"
        elif current.task_type == "model_install":
            event_type = "model_operation"
            if current.state == "failed":
                level = "error"
            elif current.state == "cancelled":
                level = "warning"
        elif current.state != previous.state:
            event_type = {
                "running": "task_started",
                "completed": "task_completed",
                "failed": "task_failed",
                "cancelled": "task_cancelled",
                "skipped": "task_skipped",
                "pending": "task_retried",
            }.get(current.state, "task_updated")
            if current.state == "failed":
                level = "error"
            elif current.state == "cancelled":
                level = "warning"
        elif current.stage != previous.stage and current.stage is not None:
            event_type = "stage_started"
        elif current.progress != previous.progress:
            event_type = "stage_progress"
        else:
            event_type = "task_updated"

        data: dict[str, object] = {
            "state": current.state,
            "progress": current.progress,
        }
        if current.error is not None:
            data["error"] = dict(current.error)
        if current.task_type == "model_install":
            spec = self._task_specs[current.task_id]
            data.update(
                {
                    "operation": spec.execution_profile.get("operation", "install"),
                    "model_id": spec.execution_profile.get("model_id", ""),
                }
            )
        self._append_event(
            current,
            event_type=event_type,
            level=level,
            message=current.message,
            detail=current.detail or None,
            data=data,
        )

    def _append_event(
        self,
        task: TaskStatus,
        *,
        event_type: str,
        level: str = "info",
        message: str = "",
        detail: str | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        sequence = self._event_sequences.get(task.task_id, 0) + 1
        self._event_sequences[task.task_id] = sequence
        self._events.setdefault(task.task_id, []).append(
            RuntimeEvent(
                sequence=sequence,
                time=self._now(),
                level=level,
                type=event_type,
                task_id=task.task_id,
                stage=task.stage,
                message=message,
                detail=detail,
                data=dict(data or {}),
            )
        )

    @staticmethod
    def clone_task(task: TaskStatus) -> TaskStatus:
        return TaskStatus(
            task_id=task.task_id,
            state=task.state,
            stage=task.stage,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
            task_type=task.task_type,
            task_source=task.task_source,
            session_id=task.session_id,
            input_asset_id=task.input_asset_id,
            created_at=task.created_at,
            queued_at=task.queued_at,
            started_at=task.started_at,
            updated_at=task.updated_at,
            finished_at=task.finished_at,
            error=dict(task.error) if task.error is not None else None,
            artifact_set_id=task.artifact_set_id,
            retry_of_task_id=task.retry_of_task_id,
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
            retry_of_task_id=task_spec.retry_of_task_id,
            created_at=task_spec.created_at,
        )

    @staticmethod
    def clone_event(event: RuntimeEvent) -> RuntimeEvent:
        return RuntimeEvent(
            sequence=event.sequence,
            time=event.time,
            level=event.level,
            type=event.type,
            task_id=event.task_id,
            stage=event.stage,
            message=event.message,
            detail=event.detail,
            data=dict(event.data),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
