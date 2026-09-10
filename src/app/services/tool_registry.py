"""Registry facade for task-driven tool execution."""

from __future__ import annotations

import threading
from typing import Any

from src.core.orchestration import ToolTaskCatalog

from ..errors import AppExecutionError
from .audio_tool_service import AudioToolService, get_audio_tool_service
from .task_service import TaskService, get_task_dispatcher, get_task_service
from src.core.tasks import TaskDispatcher


class ToolRegistry:
    """Expose supported tool task types and dispatch them."""

    def __init__(
        self,
        audio_tool_service: AudioToolService | None = None,
        task_service: TaskService | None = None,
        catalog: ToolTaskCatalog | None = None,
        dispatcher: TaskDispatcher | None = None,
    ) -> None:
        self._audio_tool_service = audio_tool_service or get_audio_tool_service()
        self._task_service = task_service or get_task_service()
        self._catalog = catalog or ToolTaskCatalog()
        self._dispatcher = dispatcher or (
            get_task_dispatcher()
            if task_service is None
            else TaskDispatcher(
                self._task_service.registry,
                task_service=self._task_service,
            )
        )
        for tool in self._catalog.list_tools():
            self._dispatcher.register_executor(
                tool["task_type"],
                self._execute_tool,
            )

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
        return self._dispatcher.submit(spec.task_id)

    def run_task(self, task_id: str) -> dict[str, Any]:
        result = self._dispatcher.run(task_id)
        if isinstance(result, dict):
            return result
        raise AppExecutionError(f"tool task returned no result: {task_id}")

    def _execute_tool(self, task_spec, context):
        tool_name = task_spec.task_type.removeprefix("tool.")
        context.update_progress(
            self._task_service.get_task(task_spec.task_id).progress,
            message=f"running {tool_name}",
            stage=tool_name,
        )
        return self._audio_tool_service.run_tool_task_spec(
            task_spec,
            manage_lifecycle=False,
            cancel_event=context.cancel_event,
        )


_service: ToolRegistry | None = None
_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ToolRegistry()
    return _service
