"""Task-driven orchestration facade for pipeline runs."""

from __future__ import annotations

import threading

from ..dto import PipelineRequest, PipelineResult, TaskStatus
from ..errors import AppExecutionError, AppValidationError
from src.core.tasks import TaskDispatcher
from .pipeline_service import PipelineService, get_pipeline_service
from .task_service import TaskService, get_task_dispatcher, get_task_service


class PipelineTaskOrchestrator:
    """Coordinate pipeline task creation, execution, and read views."""

    def __init__(
        self,
        pipeline_service: PipelineService | None = None,
        task_service: TaskService | None = None,
        dispatcher=None,
    ) -> None:
        self._pipeline_service = pipeline_service or get_pipeline_service()
        self._task_service = task_service or get_task_service()
        self._dispatcher = dispatcher or (
            get_task_dispatcher()
            if task_service is None
            else TaskDispatcher(
                self._task_service.registry,
                task_service=self._task_service,
            )
        )
        self._dispatcher.register_executor("pipeline", self._execute_pipeline)
        self._progress_callbacks: dict[str, object] = {}
        self._progress_lock = threading.Lock()

    def create_task_spec(self, request: PipelineRequest, *, task_source: str = "manual-pipeline-run"):
        return self._pipeline_service.create_pipeline_task_spec(request, task_source=task_source)

    def run_task(self, task_id: str, *, progress_callback=None, cancel_event=None) -> PipelineResult:
        with self._progress_lock:
            if progress_callback is not None:
                self._progress_callbacks[task_id] = progress_callback
        try:
            result = self._dispatcher.run(task_id, cancel_event=cancel_event)
        finally:
            with self._progress_lock:
                self._progress_callbacks.pop(task_id, None)
        if isinstance(result, PipelineResult):
            return result
        raise AppExecutionError(f"pipeline task returned no result: {task_id}")

    def submit_task(
        self,
        request: PipelineRequest,
        *,
        task_source: str = "desktop-workbench",
    ) -> TaskStatus:
        """Create and launch a pipeline task while returning its queued snapshot."""
        task, _ = self._pipeline_service.create_pipeline_task(
            request,
            task_source=task_source,
        )
        self.start_task(task.task_id)
        # Preserve the existing accepted-response snapshot: callers receive
        # the queued Task V1 record while the dispatcher owns the transition.
        return task

    def start_task(self, task_id: str) -> TaskStatus:
        """Launch one pending task in a background thread and return immediately."""
        try:
            return self._dispatcher.submit(task_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def request_cancel(self, task_id: str) -> TaskStatus:
        """Request cooperative cancellation without claiming it already stopped."""
        try:
            return self._dispatcher.request_cancel(task_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def retry_task(self, task_id: str) -> TaskStatus:
        """Create a new task from a failed/cancelled pipeline task and launch it."""
        previous = self._task_service.get_task(task_id)
        if previous.state not in {"failed", "cancelled"}:
            raise AppValidationError(f"cannot retry task in state: {previous.state}")
        if self._task_service.is_restored_history(task_id):
            raise AppValidationError(
                "historical tasks cannot be retried after restart; submit a new pipeline run"
            )
        retried = self._task_service.retry_task(task_id)
        self.start_task(retried.task_id)
        return self._task_service.get_task(retried.task_id)

    def _execute_pipeline(self, task_spec, context):
        """Adapter keeping PipelineService's domain logic behind TaskDispatcher."""
        method = getattr(self._pipeline_service, "run_pipeline_task_spec", None)
        if method is not None:
            with self._progress_lock:
                progress_callback = self._progress_callbacks.get(task_spec.task_id)
            return method(
                task_spec,
                progress_callback=progress_callback,
                cancel_event=context.cancel_event,
                manage_lifecycle=False,
            )
        return self._pipeline_service.run_pipeline_task(
            task_spec.task_id,
            cancel_event=context.cancel_event,
        )

    def get_task(self, task_id: str) -> TaskStatus:
        return self._task_service.get_task(task_id)


_service: PipelineTaskOrchestrator | None = None
_lock = threading.Lock()


def get_pipeline_task_orchestrator() -> PipelineTaskOrchestrator:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PipelineTaskOrchestrator()
    return _service
