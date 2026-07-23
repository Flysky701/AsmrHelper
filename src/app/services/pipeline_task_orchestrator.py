"""Task-driven orchestration facade for pipeline runs."""

from __future__ import annotations

import threading
import logging

from ..dto import PipelineRequest, PipelineResult, TaskStatus
from ..errors import AppValidationError
from .artifact_service import ArtifactService, get_artifact_service
from .pipeline_service import PipelineService, get_pipeline_service
from .task_service import TaskService, get_task_service


logger = logging.getLogger(__name__)


class PipelineTaskOrchestrator:
    """Coordinate pipeline task creation, execution, and read views."""

    def __init__(
        self,
        pipeline_service: PipelineService | None = None,
        task_service: TaskService | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self._pipeline_service = pipeline_service or get_pipeline_service()
        self._task_service = task_service or get_task_service()
        self._artifact_service = artifact_service or get_artifact_service()
        self._launch_lock = threading.Lock()
        self._launching_task_ids: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}

    def create_task_spec(self, request: PipelineRequest, *, task_source: str = "manual-pipeline-run"):
        return self._pipeline_service.create_pipeline_task_spec(request, task_source=task_source)

    def run_task(self, task_id: str) -> PipelineResult:
        with self._launch_lock:
            cancel_event = self._cancel_events.get(task_id)
        return self._pipeline_service.run_pipeline_task(
            task_id,
            cancel_event=cancel_event,
        )

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
        return task

    def start_task(self, task_id: str) -> TaskStatus:
        """Launch one pending task in a background thread and return immediately."""
        with self._launch_lock:
            task = self._task_service.get_task(task_id)
            if task.state == "pending":
                if task_id not in self._launching_task_ids:
                    self._launching_task_ids.add(task_id)
                    self._cancel_events[task_id] = threading.Event()
                    self._task_service.start_task(
                        task_id,
                        message="pipeline accepted by backend",
                        stage="prepare",
                    )
                    threading.Thread(
                        target=self._run_task_in_background,
                        args=(task_id,),
                        name=f"pipeline-{task_id}",
                        daemon=True,
                    ).start()
            elif task.state not in {"running"}:
                raise AppValidationError(
                    f"pipeline task cannot be started from state: {task.state}"
                )
            return task

    def request_cancel(self, task_id: str) -> TaskStatus:
        """Request cooperative cancellation without claiming it already stopped."""
        task = self._task_service.get_task(task_id)
        if task.state == "pending":
            return self._task_service.cancel_task(task_id)
        if task.state != "running":
            raise AppValidationError(f"cannot cancel task in state: {task.state}")

        with self._launch_lock:
            cancel_event = self._cancel_events.get(task_id)
            if cancel_event is None:
                cancel_event = threading.Event()
                self._cancel_events[task_id] = cancel_event
            cancel_event.set()
        return self._task_service.update_progress(
            task_id,
            progress=task.progress,
            message="cancellation requested",
            stage=task.stage,
        )

    def retry_task(self, task_id: str) -> TaskStatus:
        """Create a new task from a failed/cancelled pipeline task and launch it."""
        previous = self._task_service.get_task(task_id)
        if previous.state not in {"failed", "cancelled"}:
            raise AppValidationError(f"cannot retry task in state: {previous.state}")
        if self._task_service.is_restored_history(task_id):
            raise AppValidationError(
                "historical tasks cannot be retried after restart; submit a new pipeline run"
            )
        previous_spec = self._task_service.get_task_spec(task_id)
        _, retried = self._task_service.create_task_spec(
            task_type=previous_spec.task_type,
            task_source=f"retry:{task_id}",
            session_id=previous_spec.session_id,
            input_asset_id=previous_spec.input_asset_id,
            companion_asset_ids=previous_spec.companion_asset_ids,
            execution_profile=previous_spec.execution_profile,
            priority=previous_spec.priority,
            dedupe_key="",
        )
        self.start_task(retried.task_id)
        return retried

    def _run_task_in_background(self, task_id: str) -> None:
        try:
            self.run_task(task_id)
        except Exception:
            # PipelineService has already persisted the task failure and its detail.
            logger.exception("Background pipeline task %s failed", task_id)
        finally:
            with self._launch_lock:
                self._launching_task_ids.discard(task_id)
                self._cancel_events.pop(task_id, None)

    def get_task(self, task_id: str) -> TaskStatus:
        return self._task_service.get_task(task_id)

    def get_task_result(self, task_id: str) -> dict:
        return self._artifact_service.get_task_result_view(task_id)

    def get_task_artifacts(self, task_id: str):
        return self._artifact_service.get_task_artifacts(task_id)


_service: PipelineTaskOrchestrator | None = None
_lock = threading.Lock()


def get_pipeline_task_orchestrator() -> PipelineTaskOrchestrator:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PipelineTaskOrchestrator()
    return _service
