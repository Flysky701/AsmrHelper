"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading
from src.core.tasks import ExecutorRegistry, RuntimeEvent, TaskRegistry, TaskSpec, TaskStatus
from ..errors import AppExecutionError, AppValidationError
from ..persistence import SqliteStateStore, get_state_store


class TaskService:
    """Track application tasks in memory for the current process."""

    def __init__(
        self,
        max_concurrent: int = 4,
        state_store: SqliteStateStore | None = None,
        executor_registry: ExecutorRegistry | None = None,
    ) -> None:
        self._registry = TaskRegistry(
            max_concurrent=max_concurrent,
            executor_registry=executor_registry,
        )
        self._lock = threading.Lock()
        self._state_store = state_store
        self._restored_task_ids: set[str] = set()
        if self._state_store is not None:
            self._state_store.purge_unfinished()
            for task_spec, task_status in self._state_store.load_terminal_tasks():
                self._registry.restore_task(task_spec, task_status)
                self._restored_task_ids.add(task_status.task_id)

    def create_task_spec(
        self,
        *,
        task_type: str,
        task_source: str,
        session_id: str,
        input_asset_id: str = "",
        companion_asset_ids: list[str] | None = None,
        execution_profile: dict | None = None,
        priority: int = 0,
        dedupe_key: str = "",
        retry_of_task_id: str | None = None,
    ) -> tuple[TaskSpec, TaskStatus]:
        with self._lock:
            try:
                result = self._registry.create_task_spec(
                    task_type=task_type,
                    task_source=task_source,
                    session_id=session_id,
                    input_asset_id=input_asset_id,
                    companion_asset_ids=companion_asset_ids,
                    execution_profile=execution_profile,
                    priority=priority,
                    dedupe_key=dedupe_key,
                    retry_of_task_id=retry_of_task_id,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            if self._state_store is not None:
                try:
                    self._state_store.save_task(*result)
                except Exception as exc:
                    self._registry.discard_task(result[0].task_id)
                    raise AppExecutionError(
                        f"failed to persist task creation: {result[0].task_id}"
                    ) from exc
            return result

    def get_task(self, task_id: str) -> TaskStatus:
        with self._lock:
            try:
                return self._registry.get_task(task_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_task_spec(self, task_id: str) -> TaskSpec:
        with self._lock:
            try:
                return self._registry.get_task_spec(task_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def start_task(
        self, task_id: str, message: str = "", *, stage: str | None = "prepare"
    ) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.start_task(task_id, message=message, stage=stage)
        )

    def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str = "",
        *,
        stage: str | None = None,
        detail: str | None = None,
    ) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.update_progress(
                task_id,
                progress,
                message=message,
                stage=stage,
                detail=detail,
            )
        )

    def complete_task(
        self,
        task_id: str,
        message: str = "",
        detail: str = "",
        *,
        stage: str | None = None,
        artifact_set_id: str | None = None,
    ) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.complete_task(
                task_id,
                message=message,
                detail=detail,
                stage=stage,
                artifact_set_id=artifact_set_id,
            )
        )

    def fail_task(
        self,
        task_id: str,
        message: str,
        detail: str = "",
        *,
        stage: str | None = None,
        error: dict[str, object] | None = None,
    ) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.fail_task(
                task_id,
                message=message,
                detail=detail,
                stage=stage,
                error=error,
            )
        )

    def skip_task(self, task_id: str, message: str = "", detail: str = "") -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.skip_task(task_id, message=message, detail=detail),
        )

    def cancel_task(self, task_id: str, message: str = "cancelled by user") -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.cancel_task(task_id, message=message),
        )

    def retry_task(self, task_id: str, message: str = "queued for retry") -> TaskStatus:
        with self._lock:
            if task_id in self._restored_task_ids:
                raise AppValidationError(
                    "historical tasks cannot be retried after restart; submit a new task"
                )
            try:
                result = self._registry.retry_task(task_id, message=message)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            if self._state_store is not None:
                try:
                    task_spec = self._registry.get_task_spec(result.task_id)
                    self._state_store.save_task(task_spec, result)
                except Exception as exc:
                    self._registry.discard_task(result.task_id)
                    raise AppExecutionError(
                        f"failed to persist task retry: {result.task_id}"
                    ) from exc
            return result

    @property
    def registry(self) -> TaskRegistry:
        """Expose the core registry to the one shared TaskDispatcher."""
        return self._registry

    def set_review_state(self, task_id: str, review_state: str) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.set_review_state(task_id, review_state),
        )

    def set_review_note(self, task_id: str, review_note: str) -> TaskStatus:
        return self._guard(
            task_id,
            lambda: self._registry.set_review_note(task_id, review_note),
        )

    def running_count(self) -> int:
        with self._lock:
            return self._registry.running_count()

    def can_start(self) -> bool:
        with self._lock:
            return self._registry.can_start()

    def list_tasks(self, *, state: str | None = None) -> list[TaskStatus]:
        with self._lock:
            return self._registry.list_tasks(state=state)

    def get_queue_snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._registry.get_queue_snapshot()

    def _guard(self, task_id: str, fn):
        with self._lock:
            try:
                snapshot = self._registry.snapshot_task_state(task_id)
                result = fn()
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            if self._state_store is not None:
                try:
                    task_spec = self._registry.get_task_spec(result.task_id)
                    self._state_store.save_task(task_spec, result)
                except Exception as exc:
                    self._registry.restore_task_state(*snapshot)
                    restored = self._registry.get_task(result.task_id)
                    if restored.state not in self._registry.TERMINAL_STATES:
                        self._registry.fail_task(
                            result.task_id,
                            message="task state persistence failed",
                            detail=str(exc),
                            stage=restored.stage,
                            error={
                                "code": "TASK_STATE_PERSISTENCE_FAILED",
                                "stage": restored.stage or "prepare",
                                "message": "task state could not be persisted",
                                "retryable": True,
                                "detail": str(exc),
                            },
                        )
                    raise AppExecutionError(
                        f"failed to persist task state: {result.task_id}"
                    ) from exc
            return result

    def list_events(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[RuntimeEvent]:
        with self._lock:
            try:
                return self._registry.list_events(
                    task_id,
                    after_sequence=after_sequence,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def is_restored_history(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._restored_task_ids


_service: TaskService | None = None
_lock = threading.Lock()
_dispatcher = None
_dispatcher_service = None
_dispatcher_lock = threading.Lock()


def get_task_service() -> TaskService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TaskService(state_store=get_state_store())
    return _service


def get_task_dispatcher():
    """Return the one application dispatcher for the process."""
    global _dispatcher, _dispatcher_service
    service = get_task_service()
    if _dispatcher is None or _dispatcher_service is not service:
        with _dispatcher_lock:
            if _dispatcher is None or _dispatcher_service is not service:
                from src.core.tasks import TaskDispatcher

                _dispatcher = TaskDispatcher(
                    service.registry,
                    task_service=service,
                )
                _dispatcher_service = service
                # Wire lazy adapters immediately so a generic task submission
                # cannot create a valid-looking task with no executable path.
                _dispatcher.register_executor(
                    "pipeline",
                    lambda spec, context: _lazy_pipeline_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "tool.separate",
                    lambda spec, context: _lazy_tool_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "tool.convert",
                    lambda spec, context: _lazy_tool_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "tool.split",
                    lambda spec, context: _lazy_tool_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "tool.translate_subtitle",
                    lambda spec, context: _lazy_tool_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "tool.volume_preview",
                    lambda spec, context: _lazy_tool_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "subtitle.script_to_vtt",
                    lambda spec, context: _lazy_script_subtitle_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "model_install",
                    lambda spec, context: _lazy_model_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "voice.design",
                    lambda spec, context: _lazy_voice_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "voice.clone",
                    lambda spec, context: _lazy_voice_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "voice.preview",
                    lambda spec, context: _lazy_voice_executor(spec, context),
                )
    return _dispatcher


def _lazy_pipeline_executor(task_spec, context):
    from .pipeline_task_orchestrator import get_pipeline_task_orchestrator

    return get_pipeline_task_orchestrator()._execute_pipeline(task_spec, context)


def _lazy_tool_executor(task_spec, context):
    from .tool_registry import get_tool_registry

    return get_tool_registry()._execute_tool(task_spec, context)


def _lazy_model_executor(task_spec, context):
    from .model_service import get_model_service

    return get_model_service()._execute_model_install(task_spec, context)


def _lazy_script_subtitle_executor(task_spec, context):
    from .script_subtitle_service import get_script_subtitle_service

    return get_script_subtitle_service()._execute_task(task_spec, context)


def _lazy_voice_executor(task_spec, context):
    from .voice_service import get_voice_service

    return get_voice_service()._execute_voice_task(task_spec, context)
