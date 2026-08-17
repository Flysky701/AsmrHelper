"""Lightweight in-process task dispatcher.

The dispatcher is the single execution boundary for long-running Task V1
work.  It owns start-once semantics, cooperative cancellation, final status
transitions, and executor lookup; domain services remain responsible for the
actual pipeline/model/tool work and artifact registration.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import logging
import threading
from typing import Any, Callable

from .executors import ExecutorRegistry, TaskExecutionContext
from .models import TaskSpec, TaskStatus
from .service import TaskRegistry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ExecutionRecord:
    cancel_event: threading.Event
    thread: threading.Thread | None = None
    result: Any = None
    error: BaseException | None = None


class _WorkerLaunchFailure(Exception):
    """Identify a worker construction/start failure after lifecycle start succeeded."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


class TaskDispatcher:
    """Dispatch registered tasks synchronously or on one background thread."""

    def __init__(
        self,
        registry: TaskRegistry,
        *,
        task_service: Any | None = None,
        executor_registry: ExecutorRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._task_service = task_service
        self._executor_registry = executor_registry or registry.executor_registry
        self._executors = self._executor_registry
        self._lock = threading.RLock()
        self._records: dict[str, _ExecutionRecord] = {}

    @property
    def executor_registry(self) -> ExecutorRegistry:
        return self._executor_registry

    def register_executor(self, task_type: str, executor: Callable[..., Any]) -> None:
        """Register or replace the concrete handler for a task type."""
        self._executor_registry.register(task_type, executor)

    def resolve_executor(self, task_type: str) -> Callable[..., Any] | None:
        return self._executor_registry.resolve(task_type)

    def can_dispatch(self) -> bool:
        return self._lifecycle().can_start() and bool(self._get_next_pending())

    def dispatch_next(self) -> TaskStatus | None:
        if not self._lifecycle().can_start():
            return None
        task_spec = self._get_next_pending()
        if task_spec is None:
            return None
        record = self._begin(task_spec.task_id, require_capacity=True)
        if record is None:
            return None
        self._execute(task_spec)
        return self._lifecycle().get_task(task_spec.task_id)

    def dispatch_all_pending(self) -> list[TaskStatus]:
        results: list[TaskStatus] = []
        while self._lifecycle().can_start():
            status = self.dispatch_next()
            if status is None:
                break
            results.append(status)
        return results

    def submit(self, task_id: str) -> TaskStatus:
        """Start one pending task in the background and return its snapshot."""
        task = self._lifecycle().get_task(task_id)
        if task.state == "running":
            return task
        if task.state != "pending":
            raise ValueError(f"task cannot be submitted from state: {task.state}")

        task_spec = self._lifecycle().get_task_spec(task_id)
        try:
            self._start_background(task_spec)
        except _WorkerLaunchFailure as exc:
            # No worker exists to release the newly freed slot, so continue the
            # queue here. Lifecycle/persistence failures intentionally do not
            # drain: a broken state store must not fail every pending task.
            self._drain_pending()
            raise exc.cause
        return self._lifecycle().get_task(task_id)

    def run(self, task_id: str, *, cancel_event: threading.Event | None = None) -> Any:
        """Run a task now, or wait for its already submitted execution."""
        task = self._lifecycle().get_task(task_id)
        if task.state == "pending":
            task_spec = self._lifecycle().get_task_spec(task_id)
            record = self._begin(task_id, require_capacity=True)
            if record is None:
                raise ValueError("task cannot run while execution capacity is exhausted")
            if cancel_event is not None:
                record.cancel_event = cancel_event
            self._execute(task_spec)
        elif task.state == "running":
            if cancel_event is not None and cancel_event.is_set():
                self.request_cancel(task_id)
            record = self._records.get(task_id)
            if record is None or record.thread is None:
                raise ValueError(f"task is already running without a dispatcher worker: {task_id}")
            if record.thread is not threading.current_thread():
                record.thread.join()
        elif task.state not in self._registry.TERMINAL_STATES:
            raise ValueError(f"task cannot be run from state: {task.state}")

        record = self._records.get(task_id)
        if record is not None and record.error is not None:
            raise record.error
        if record is not None:
            return record.result
        return self._lifecycle().get_task(task_id)

    def request_cancel(self, task_id: str) -> TaskStatus:
        """Request cancellation; final ``cancelled`` waits for executor exit."""
        task = self._lifecycle().get_task(task_id)
        if task.state == "pending":
            return self._lifecycle().cancel_task(task_id)
        if task.state != "running":
            raise ValueError(f"cannot cancel task in state: {task.state}")

        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise ValueError(f"task is running outside the dispatcher: {task_id}")
            record.cancel_event.set()
        return self._lifecycle().update_progress(
            task_id,
            task.progress,
            message="cancellation requested",
            stage=task.stage,
        )

    def cancel_event(self, task_id: str) -> threading.Event | None:
        with self._lock:
            record = self._records.get(task_id)
            return record.cancel_event if record else None

    def _begin(
        self,
        task_id: str,
        *,
        require_capacity: bool = False,
    ) -> _ExecutionRecord | None:
        with self._lock:
            if task_id in self._records:
                raise ValueError(f"task has already been started: {task_id}")
            lifecycle = self._lifecycle()
            if require_capacity:
                start_if_capacity = getattr(lifecycle, "start_task_if_capacity", None)
                if start_if_capacity is not None:
                    started = start_if_capacity(
                        task_id,
                        message="task accepted by executor registry",
                    )
                    if started is None:
                        return None
                else:
                    if not lifecycle.can_start():
                        return None
                    lifecycle.start_task(
                        task_id,
                        message="task accepted by executor registry",
                    )
            else:
                lifecycle.start_task(
                    task_id,
                    message="task accepted by executor registry",
                )
            record = _ExecutionRecord(cancel_event=threading.Event())
            self._records[task_id] = record
            return record

    def _execute(self, task_spec: TaskSpec) -> None:
        task_id = task_spec.task_id
        record = self._records[task_id]
        executor = self.resolve_executor(task_spec.task_type)
        if executor is None:
            exc = RuntimeError(f"no executor registered for task_type: {task_spec.task_type}")
            record.error = exc
            self._finalize_failure(task_id, exc)
            return

        context = TaskExecutionContext(
            task_id=task_id,
            cancel_event=record.cancel_event,
            update_progress_callback=lambda progress, message="", **kwargs: self._lifecycle().update_progress(
                task_id,
                progress,
                message=message,
                **kwargs,
            ),
            set_stage_callback=lambda stage: self._lifecycle().update_progress(
                task_id,
                self._lifecycle().get_task(task_id).progress,
                stage=stage,
            ),
        )
        try:
            record.result = self._invoke_executor(executor, task_spec, context)
            current = self._lifecycle().get_task(task_id)
            if current.state in self._registry.TERMINAL_STATES:
                return
            if record.cancel_event.is_set():
                self._lifecycle().cancel_task(task_id, message="cancelled by user")
            else:
                detail, artifact_set_id = self._result_metadata(record.result, task_id)
                self._lifecycle().complete_task(
                    task_id,
                    message="completed",
                    detail=detail,
                    stage=current.stage,
                    artifact_set_id=artifact_set_id,
                )
        except BaseException as exc:  # worker errors must always close the task
            record.error = exc
            current = self._lifecycle().get_task(task_id)
            if current.state in self._registry.TERMINAL_STATES:
                return
            if record.cancel_event.is_set():
                self._lifecycle().cancel_task(task_id, message="cancelled by user")
            else:
                self._finalize_failure(task_id, exc, stage=current.stage)
        finally:
            with self._lock:
                if record.thread is None and threading.current_thread() is not threading.main_thread():
                    record.thread = threading.current_thread()
            self._drain_pending()

    def _start_background(self, task_spec: TaskSpec) -> bool:
        with self._lock:
            current = self._lifecycle().get_task(task_spec.task_id)
            if current.state == "running":
                return False
            if current.state != "pending":
                raise ValueError(f"task cannot be submitted from state: {current.state}")

            record = self._begin(task_spec.task_id, require_capacity=True)
            if record is None:
                return False
            try:
                thread = threading.Thread(
                    target=self._execute,
                    args=(task_spec,),
                    name=f"task-{task_spec.task_id}",
                    daemon=True,
                )
                record.thread = thread
                thread.start()
            except BaseException as exc:
                record.thread = None
                record.error = exc
                self._finalize_failure(task_spec.task_id, exc, stage="prepare")
                raise _WorkerLaunchFailure(exc) from exc
            return True

    def _drain_pending(self) -> None:
        """Start queued work whenever a running slot is released."""
        while self._lifecycle().can_start():
            task_spec = self._get_next_pending()
            if task_spec is None:
                return
            try:
                started = self._start_background(task_spec)
                if not started:
                    if self._lifecycle().get_task(task_spec.task_id).state == "pending":
                        return
                    continue
            except _WorkerLaunchFailure:
                # The failed task is terminal and its slot is free; keep
                # scanning so one broken thread launch does not block the queue.
                continue
            except Exception:
                # A concurrent caller may have started/cancelled the task, or
                # TaskService may have quarantined it after persistence failed.
                # Re-scan only for a concurrent terminal transition. A failed
                # lifecycle start can mean the state store is unavailable, in
                # which case draining would quarantine the entire queue.
                try:
                    state = self._lifecycle().get_task(task_spec.task_id).state
                except ValueError:
                    return
                if state in {"cancelled", "skipped", "completed"}:
                    continue
                return

    @staticmethod
    def _invoke_executor(
        executor: Callable[..., Any],
        task_spec: TaskSpec,
        context: TaskExecutionContext,
    ) -> Any:
        try:
            parameters = inspect.signature(executor).parameters
        except (TypeError, ValueError):
            parameters = {}
        if len(parameters) >= 2:
            return executor(task_spec, context)
        return executor(task_spec)

    def _finalize_failure(
        self,
        task_id: str,
        exc: BaseException,
        *,
        stage: str | None = None,
    ) -> None:
        structured_error = getattr(exc, "task_error", None)
        if isinstance(structured_error, dict):
            resolved_stage = str(
                structured_error.get("stage")
                or stage
                or self._lifecycle().get_task(task_id).stage
                or "prepare"
            )
            self._lifecycle().fail_task(
                task_id,
                message=str(structured_error.get("message") or str(exc)),
                detail=str(structured_error.get("detail") or str(exc)),
                stage=resolved_stage,
                error=dict(structured_error),
            )
            return
        detail = str(getattr(exc, "detail", "") or str(exc))
        resolved_stage = stage or self._lifecycle().get_task(task_id).stage or "prepare"
        self._lifecycle().fail_task(
            task_id,
            message="execution failed",
            detail=detail,
            stage=resolved_stage,
            error={
                "code": "TASK_EXECUTION_FAILED",
                "stage": resolved_stage,
                "message": detail,
                "retryable": True,
                "detail": detail,
            },
        )

    @staticmethod
    def _result_metadata(result: Any, task_id: str) -> tuple[str, str | None]:
        if isinstance(result, dict):
            detail = str(result.get("primary_output") or result.get("detail") or "")
            artifact_set_id = result.get("artifact_set_id")
            return detail, str(artifact_set_id) if artifact_set_id else None
        detail = str(getattr(result, "mix_path", "") or getattr(result, "primary_output", "") or "")
        return detail, task_id if getattr(result, "artifacts", None) else None

    def _get_next_pending(self) -> TaskSpec | None:
        pending = self._lifecycle().list_tasks(state="pending")
        if not pending:
            return None
        pending.sort(
            key=lambda task: (
                -self._lifecycle().get_task_spec(task.task_id).priority,
                task.task_id,
            )
        )
        return self._lifecycle().get_task_spec(pending[0].task_id)

    def _lifecycle(self) -> Any:
        return self._task_service or self._registry
