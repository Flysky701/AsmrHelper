"""Registry facade for task-driven tool execution."""

from __future__ import annotations

import threading
from typing import Any

from ..dto import TaskStatus
from .artifact_service import ArtifactService, get_artifact_service
from .audio_tool_service import AudioToolService, get_audio_tool_service
from .task_service import TaskService, get_task_service


class ToolRegistry:
    """Expose supported tool task types and dispatch them."""

    _TOOLS: dict[str, dict[str, Any]] = {
        "tool.separate": {"name": "separate", "category": "audio", "primary_artifact": "audio.vocals"},
        "tool.convert": {"name": "convert", "category": "audio", "primary_artifact": "audio.converted"},
        "tool.split": {"name": "split", "category": "audio", "primary_artifact": "audio.segment_collection"},
        "tool.translate_subtitle": {"name": "translate_subtitle", "category": "subtitle", "primary_artifact": "subtitle.translated"},
        "tool.volume_preview": {"name": "volume_preview", "category": "analysis", "primary_artifact": ""},
    }

    def __init__(
        self,
        audio_tool_service: AudioToolService | None = None,
        task_service: TaskService | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self._audio_tool_service = audio_tool_service or get_audio_tool_service()
        self._task_service = task_service or get_task_service()
        self._artifact_service = artifact_service or get_artifact_service()

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"task_type": task_type, **meta}
            for task_type, meta in sorted(self._TOOLS.items())
        ]

    def get_tool(self, task_type: str) -> dict[str, Any]:
        meta = self._TOOLS.get(task_type)
        if meta is None:
            raise ValueError(f"unsupported tool task type: {task_type}")
        return {"task_type": task_type, **meta}

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
