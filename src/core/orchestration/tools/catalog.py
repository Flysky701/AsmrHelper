"""Core tool orchestration metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class ToolTaskDefinition:
    task_type: str
    name: str
    category: str
    primary_artifact: str = ""


class ToolTaskCatalog:
    """Catalog of task-driven tool definitions."""

    _TOOLS: tuple[ToolTaskDefinition, ...] = (
        ToolTaskDefinition(
            task_type="tool.separate",
            name="separate",
            category="audio",
            primary_artifact="audio.vocals",
        ),
        ToolTaskDefinition(
            task_type="tool.convert",
            name="convert",
            category="audio",
            primary_artifact="audio.converted",
        ),
        ToolTaskDefinition(
            task_type="tool.split",
            name="split",
            category="audio",
            primary_artifact="audio.segment_collection",
        ),
        ToolTaskDefinition(
            task_type="tool.translate_subtitle",
            name="translate_subtitle",
            category="subtitle",
            primary_artifact="subtitle.translated",
        ),
        ToolTaskDefinition(
            task_type="tool.volume_preview",
            name="volume_preview",
            category="analysis",
            primary_artifact="",
        ),
    )

    def list_tools(self) -> list[dict[str, str]]:
        return [asdict(tool) for tool in self._TOOLS]

    def get_tool(self, task_type: str) -> dict[str, str]:
        for tool in self._TOOLS:
            if tool.task_type == task_type:
                return asdict(tool)
        raise ValueError(f"unsupported tool task type: {task_type}")
