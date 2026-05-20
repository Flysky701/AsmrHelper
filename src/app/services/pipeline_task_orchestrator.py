"""Task-driven orchestration facade for pipeline runs."""

from __future__ import annotations

import threading

from ..dto import PipelineRequest, PipelineResult, TaskStatus
from .artifact_service import ArtifactService, get_artifact_service
from .pipeline_service import PipelineService, get_pipeline_service
from .task_service import TaskService, get_task_service


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

    def create_task_spec(self, request: PipelineRequest, *, task_source: str = "manual-pipeline-run"):
        return self._pipeline_service.create_pipeline_task_spec(request, task_source=task_source)

    def run_task(self, task_id: str) -> PipelineResult:
        return self._pipeline_service.run_pipeline_task(task_id)

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
