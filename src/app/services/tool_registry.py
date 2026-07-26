"""Registry facade for task-driven tool execution."""

from __future__ import annotations

import threading
from typing import Any

from src.core.orchestration import ToolTaskCatalog

from ..dto import TaskStatus
from .artifact_service import ArtifactService, get_artifact_service
from .audio_tool_service import AudioToolService, get_audio_tool_service
from .task_service import TaskService, get_task_service


class ToolRegistry:
    """Expose supported tool task types and dispatch them."""

    def __init__(
        self,
        audio_tool_service: AudioToolService | None = None,
        task_service: TaskService | None = None,
        artifact_service: ArtifactService | None = None,
        catalog: ToolTaskCatalog | None = None,
    ) -> None:
        self._audio_tool_service = audio_tool_service or get_audio_tool_service()
        self._task_service = task_service or get_task_service()
        self._artifact_service = artifact_service or get_artifact_service()
        self._catalog = catalog or ToolTaskCatalog()

    def list_tools(self) -> list[dict[str, Any]]:
        return self._catalog.list_tools()

    def get_tool(self, task_type: str) -> dict[str, Any]:
        return self._catalog.get_tool(task_type)

    def create_task(
        self,
        *,
        task_type: str,
        input_path: str,
        execution_profile: dict[str, Any],
        companion_paths: list[str] | None = None,
    ):
        self.get_tool(task_type)
        spec = self._audio_tool_service.create_tool_task_spec(
            task_type=task_type,
            input_path=input_path,
            execution_profile=execution_profile,
            companion_paths=companion_paths,
            task_source="desktop-tool-run",
        )
        return self._task_service.get_task(spec.task_id)

    def run_task(self, task_id: str) -> dict[str, Any]:
        return self._audio_tool_service.run_tool_task(task_id)

    def get_task(self, task_id: str) -> TaskStatus:
        return self._task_service.get_task(task_id)

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        return self._artifact_service.get_task_result_view(task_id)

    def get_task_artifacts(self, task_id: str):
        return self._artifact_service.get_task_artifacts(task_id)


_service: ToolRegistry | None = None
_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ToolRegistry()
    return _service
