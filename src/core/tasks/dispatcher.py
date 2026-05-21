"""Task dispatcher — routes pending tasks to registered executors.

This module provides the dispatch mechanism that connects the task queue
(TaskRegistry) to actual execution logic. Each task_type is mapped to
an executor callable that performs the work.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .models import TaskSpec, TaskStatus
from .service import TaskRegistry

logger = logging.getLogger(__name__)

# Executor signature: (task_spec: TaskSpec) -> dict[str, Any]
TaskExecutor = Callable[[TaskSpec], dict[str, Any]]


class TaskDispatcher:
    """Dispatch pending tasks to registered executors by task_type.

    This is a lightweight in-process dispatcher. It does NOT implement
    persistent queues or distributed execution — those are out of scope
    for the current architecture.

    Usage:
        dispatcher = TaskDispatcher(registry)
        dispatcher.register_executor("pipeline", pipeline_executor_fn)
        dispatcher.register_executor("tool.separate", separation_executor_fn)
        dispatcher.dispatch_next()  # picks highest-priority pending task
    """

    def __init__(self, registry: TaskRegistry) -> None:
        self._registry = registry
        self._executors: dict[str, TaskExecutor] = {}
        self._prefix_executors: dict[str, TaskExecutor] = {}
        self._lock = threading.Lock()

    def register_executor(self, task_type: str, executor: TaskExecutor) -> None:
        """Register an executor for a specific task_type.

        Args:
            task_type: Exact task type (e.g., "pipeline") or prefix pattern
                       ending with "." (e.g., "tool." matches "tool.separate", "tool.convert")
            executor: Callable that accepts a TaskSpec and returns a result dict
        """
        with self._lock:
            if task_type.endswith("."):
                self._prefix_executors[task_type] = executor
            else:
                self._executors[task_type] = executor

    def resolve_executor(self, task_type: str) -> TaskExecutor | None:
        """Find the executor for a given task_type."""
        # Exact match first
        executor = self._executors.get(task_type)
        if executor:
            return executor
        # Prefix match
        for prefix, exec_fn in self._prefix_executors.items():
            if task_type.startswith(prefix):
                return exec_fn
        return None

    def can_dispatch(self) -> bool:
        """Check if there are pending tasks and capacity to run them."""
        return self._registry.can_start() and bool(self._get_next_pending())

    def dispatch_next(self) -> TaskStatus | None:
        """Pick the highest-priority pending task and execute it.

        Returns:
            The final TaskStatus after execution, or None if nothing to dispatch.
        """
        if not self._registry.can_start():
            logger.debug("dispatch_next: at max concurrency, skipping")
            return None

        task_spec = self._get_next_pending()
        if task_spec is None:
            return None

        executor = self.resolve_executor(task_spec.task_type)
        if executor is None:
            logger.warning("no executor registered for task_type=%s", task_spec.task_type)
            return self._registry.fail_task(
                task_spec.task_id,
                message=f"no executor for task_type: {task_spec.task_type}",
            )

        return self._execute(task_spec, executor)

    def dispatch_all_pending(self) -> list[TaskStatus]:
        """Dispatch all pending tasks that have capacity.

        Returns:
            List of final TaskStatus for each dispatched task.
        """
        results: list[TaskStatus] = []
        while self._registry.can_start():
            status = self.dispatch_next()
            if status is None:
                break
            results.append(status)
        return results

    def _get_next_pending(self) -> TaskSpec | None:
        """Get the highest-priority pending task."""
        pending = self._registry.list_tasks(state="pending")
        if not pending:
            return None

        # Sort by priority (higher first), then by task_id (FIFO for same priority)
        pending.sort(key=lambda t: (-self._get_priority(t.task_id), t.task_id))
        return self._registry.get_task_spec(pending[0].task_id)

    def _get_priority(self, task_id: str) -> int:
        """Get priority for a task."""
        try:
            spec = self._registry.get_task_spec(task_id)
            return spec.priority
        except ValueError:
            return 0

    def _execute(self, task_spec: TaskSpec, executor: TaskExecutor) -> TaskStatus:
        """Execute a task and handle lifecycle transitions."""
        self._registry.start_task(task_spec.task_id, message="dispatched")

        try:
            result = executor(task_spec)
            detail = ""
            if isinstance(result, dict):
                detail = result.get("primary_output", "") or result.get("detail", "")
            return self._registry.complete_task(
                task_spec.task_id,
                message="completed",
                detail=str(detail),
            )
        except Exception as exc:
            logger.exception("task %s failed: %s", task_spec.task_id, exc)
            return self._registry.fail_task(
                task_spec.task_id,
                message="execution failed",
                detail=str(exc),
            )
