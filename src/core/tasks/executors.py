"""Small in-process executor registry shared by task submission and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable


TaskExecutor = Callable[..., Any]


@dataclass(slots=True)
class TaskExecutionContext:
    """Callbacks and cancellation state available to one executor invocation."""

    task_id: str
    cancel_event: threading.Event
    update_progress_callback: Callable[..., Any]
    set_stage_callback: Callable[[str], Any]

    @property
    def cancellation_requested(self) -> bool:
        return self.cancel_event.is_set()

    def update_progress(
        self,
        progress: float,
        message: str = "",
        *,
        stage: str | None = None,
        detail: str | None = None,
    ) -> Any:
        if stage is not None:
            self.set_stage_callback(stage)
        return self.update_progress_callback(
            progress,
            message,
            stage=stage,
            detail=detail,
        )


class ExecutorRegistry:
    """Register exact task types or explicit prefixes for this process.

    A registration may be created before its callable is wired.  This lets the
    task domain reject unknown types at submission time while application
    services attach their concrete handlers during startup.  Dispatch still
    refuses a registration without a callable, so a task cannot remain pending
    forever because a handler was only declared, not connected.
    """

    def __init__(self) -> None:
        self._exact: dict[str, TaskExecutor | None] = {}
        self._prefix: dict[str, TaskExecutor | None] = {}
        self._lock = threading.RLock()

    def register(self, task_type: str, executor: TaskExecutor | None = None) -> None:
        normalized = str(task_type or "").strip()
        if not normalized:
            raise ValueError("task_type is required")
        with self._lock:
            target = self._prefix if normalized.endswith(".") else self._exact
            target[normalized] = executor

    def is_registered(self, task_type: str) -> bool:
        with self._lock:
            return self._find(task_type) is not None

    def resolve(self, task_type: str) -> TaskExecutor | None:
        with self._lock:
            entry = self._find(task_type)
            return None if entry is None else entry[1]

    def registered_task_types(self) -> list[str]:
        with self._lock:
            return sorted([*self._exact, *self._prefix])

    def _find(self, task_type: str) -> tuple[str, TaskExecutor | None] | None:
        if task_type in self._exact:
            return task_type, self._exact[task_type]
        for prefix in sorted(self._prefix, key=len, reverse=True):
            if task_type.startswith(prefix):
                return prefix, self._prefix[prefix]
        return None


def build_default_executor_registry() -> ExecutorRegistry:
    """Return the supported Task V1 type allow-list.

    Concrete handlers are wired by the application facades.  Keeping the
    allow-list in the core task domain means raw task creation cannot invent a
    type that no application entrypoint knows how to execute.
    """

    registry = ExecutorRegistry()
    for task_type in (
        "pipeline",
        "tool.separate",
        "tool.convert",
        "tool.split",
        "tool.translate_subtitle",
        "tool.volume_preview",
        "model_install",
        "voice.design",
        "voice.clone",
        "voice.preview",
    ):
        registry.register(task_type)
    return registry
