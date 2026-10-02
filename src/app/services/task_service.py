"""In-memory task lifecycle service for the application layer."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from copy import deepcopy
from src.task_connection_context import capture_connections, connection_context
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
        self._lock = threading.RLock()
        self._state_store = state_store
        self._restored_task_ids: set[str] = set()
        self._connection_snapshots: dict[str, dict] = {}
        self._graph_connection_snapshots: dict[str, dict] = {}
        self._connection_records: dict[str, dict] = {}
        self.recovery_store = None
        if self._state_store is not None:
            if isinstance(self._state_store, SqliteStateStore):
                from ..persistence.recovery_store import RecoveryStore
                self.recovery_store = RecoveryStore(self._state_store)
                self.recovery_store.retain_interrupted()
            self._state_store.purge_unfinished()
            for task_spec, task_status in self._state_store.load_terminal_tasks():
                self._registry.restore_task(task_spec, task_status)
                self._restored_task_ids.add(task_status.task_id)
            if isinstance(self._state_store, SqliteStateStore):
                self._registry.reserve_deleted_ids(self._state_store.load_deleted_task_ids())

    @contextmanager
    def history_deletion_guard(self):
        with self._lock:
            yield

    def history_snapshot(self):
        with self._lock:
            return [(self._registry.get_task_spec(task.task_id), task)
                    for task in self._registry.list_tasks()]

    def forget_task_history(self, task_ids: set[str]) -> None:
        """Apply only after the persistent deletion transaction commits."""
        with self._lock:
            self._registry.delete_terminal_tasks(task_ids)
            self._restored_task_ids.difference_update(task_ids)
            for task_id in task_ids:
                self._connection_snapshots.pop(task_id, None)
                self._graph_connection_snapshots.pop(task_id, None)
                self._connection_records.pop(task_id, None)

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
        graph_prepared: bool = False,
        frozen_graph_connections: dict | None = None,
    ) -> tuple[TaskSpec, TaskStatus]:
        with self._lock:
            from src.config import config

            from src.task_connection_context import resolve_task_settings
            execution_profile = deepcopy(execution_profile)
            is_graph = (execution_profile or {}).get("version") == 2
            if is_graph and not graph_prepared:
                raise AppValidationError("节点工作流请通过 /pipeline-runs 提交，以校验素材并冻结节点配置")
            settings = config.to_dict() if is_graph else resolve_task_settings(config.to_dict(), execution_profile)
            graph_connections = {}
            if is_graph:
                from .graph_pipeline_service import freeze_graph_connections
                if frozen_graph_connections is None:
                    try:
                        execution_profile, graph_connections = freeze_graph_connections(execution_profile, settings)
                    except ValueError as exc:
                        raise AppValidationError(str(exc)) from exc
                else:
                    required = {node["id"] for node in execution_profile["graph"]["nodes"]
                                if node["kind"] == "translate"}
                    if required != set(frozen_graph_connections):
                        raise AppValidationError("frozen translation context unavailable; submit a new batch")
                    graph_connections = deepcopy(frozen_graph_connections)
            connections = {} if is_graph else capture_connections(settings)
            from src.recovery_connections import capture_recovery_connections
            connection_record = {} if is_graph else capture_recovery_connections(settings, connections, include_tts=False)
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
            # A deduplicated submission must keep the first task's connections.
            self._connection_snapshots.setdefault(result[0].task_id, connections)
            if is_graph:
                self._graph_connection_snapshots.setdefault(result[0].task_id, graph_connections)
            self._connection_records.setdefault(result[0].task_id, connection_record)
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

    def start_task_if_capacity(
        self, task_id: str, message: str = "", *, stage: str | None = "prepare"
    ) -> TaskStatus | None:
        """Atomically reserve one execution slot and transition a pending task."""
        with self._lock:
            try:
                if self._registry.get_task(task_id).state != "pending":
                    return None
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            if not self._registry.can_start():
                return None
            return self._guard_locked(
                task_id,
                lambda: self._registry.start_task(
                    task_id,
                    message=message,
                    stage=stage,
                ),
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

    def retry_task(self, task_id: str, message: str = "queued for retry", *, _batch_managed: bool = False) -> TaskStatus:
        with self._lock:
            if task_id in self._restored_task_ids:
                raise AppValidationError(
                    "historical tasks cannot be retried after restart; submit a new task"
                )
            try:
                task_spec = self._registry.get_task_spec(task_id)
                if task_spec.task_source.startswith("batch-run:") and not _batch_managed:
                    raise AppValidationError("retry this group from its batch controls to preserve queue membership")
                error = self._registry.get_task(task_id).error or {}
                if error.get("result_unknown"):
                    raise AppValidationError("上次请求结果未知，请确认服务端结果与计费后在音色实验室显式生成新候选")
                if task_id not in self._connection_snapshots:
                    raise AppValidationError("original private task snapshot unavailable; submit a new task")
                if task_spec.execution_profile.get("version") == 2:
                    required = {node["id"] for node in task_spec.execution_profile["graph"]["nodes"]
                                if node["kind"] == "translate"}
                    if (task_id not in self._graph_connection_snapshots
                            or required != set(self._graph_connection_snapshots[task_id])):
                        raise AppValidationError("original private graph snapshot unavailable; submit a new task")
                if task_spec.task_type == "voice.clone" and any(
                    task.retry_of_task_id == task_id
                    for task in self._registry.list_tasks()
                ):
                    raise AppValidationError(
                        "voice clone retry already exists; retry the latest failed task instead"
                    )
                result = self._registry.retry_task(task_id, message=message)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            if self._state_store is not None:
                try:
                    task_spec = self._registry.get_task_spec(result.task_id)
                    manifest = self.recovery_store.manifest(task_id) if self.recovery_store else None
                    if manifest:
                        manifest["resume_of_task_id"] = None
                        self._state_store.save_task(task_spec, result, recovery_manifest=manifest)
                    else:
                        self._state_store.save_task(task_spec, result)
                except Exception as exc:
                    self._registry.discard_task(result.task_id)
                    raise AppExecutionError(
                        f"failed to persist task retry: {result.task_id}"
                    ) from exc
            self._connection_snapshots[result.task_id] = deepcopy(
                self._connection_snapshots.get(task_id, {})
            )
            if task_id in self._connection_records:
                self._connection_records[result.task_id] = deepcopy(self._connection_records[task_id])
            if task_id in self._graph_connection_snapshots:
                self._graph_connection_snapshots[result.task_id] = deepcopy(self._graph_connection_snapshots[task_id])
            return result

    def graph_node_connection_context(self, task_id: str, node_id: str):
        """A selected translation instance cannot fall back to another connection."""
        with self._lock:
            snapshots = self._graph_connection_snapshots.get(task_id, {})
            if node_id not in snapshots:
                raise AppValidationError("图节点原连接快照不可用，请重新提交任务")
            snapshot = deepcopy(snapshots[node_id])
        return connection_context(snapshot)

    def connection_context(self, task_id: str):
        """Bind private connections for this task without exposing its secrets."""
        with self._lock:
            snapshot = deepcopy(self._connection_snapshots.get(task_id))
        return connection_context(snapshot)

    def save_pipeline_manifest(self, task_id: str, *, input_path: str,
                               companion_paths: list[str], output_root: str) -> None:
        """Persist enough facts to reconstruct sessions after process restart."""
        if self.recovery_store is None:
            return
        with self._lock:
            self.recovery_store.save_manifest(task_id, {
                "version": self._registry.get_task_spec(task_id).execution_profile.get("version", 1),
                "input_path": input_path,
                "companion_paths": list(companion_paths), "output_root": output_root,
                "connections": self._connection_records[task_id],
                "resume_of_task_id": None,
            })

    def recovery_info(self, task_id: str) -> dict:
        task = self.get_task(task_id)
        if self.get_task_spec(task_id).execution_profile.get("version") == 2:
            return {"can_resume": False, "reason": "图任务暂不支持阶段续跑；显式重试会重新执行全部节点",
                    "completed_stages": []}
        manifest = self.recovery_store.manifest(task_id) if self.recovery_store else None
        reason = None
        stages = []
        if task.task_type != "pipeline" or not manifest:
            reason = "此任务没有可恢复的执行清单"
        elif task.state not in {"failed", "cancelled"}:
            reason = "仅失败、取消或中断的任务可以继续"
        elif any(t.retry_of_task_id == task_id and t.state in {"pending", "running"}
                 for t in self.list_tasks()):
            reason = "该任务已有正在执行的恢复尝试"
        else:
            from src.config import config
            from src.recovery_connections import restore_recovery_connections
            from pathlib import Path
            try:
                restore_recovery_connections(manifest["connections"], config.to_dict())
                for path in [manifest["input_path"], *manifest["companion_paths"]]:
                    if not Path(path).is_file():
                        raise ValueError("原始输入文件已不存在")
            except (ValueError, KeyError) as exc:
                reason = str(exc)
        if manifest:
            stages = [stage for stage in ("separate", "asr", "align", "translate", "tts", "mix", "export")
                      if self.recovery_store.checkpoint(task_id, stage)]
        return {"can_resume": reason is None, "reason": reason, "completed_stages": stages}

    def resume_pipeline_task(self, task_id: str, *, session_id: str,
                             input_asset_id: str, companion_asset_ids: list[str]) -> TaskStatus:
        from src.config import config
        from src.recovery_connections import restore_recovery_connections
        info = self.recovery_info(task_id)
        if not info["can_resume"]:
            raise AppValidationError(info["reason"])
        with self._lock:
            if any(t.retry_of_task_id == task_id and t.state in {"pending", "running"}
                   for t in self._registry.list_tasks()):
                raise AppValidationError("该任务已有正在执行的恢复尝试")
            previous = self._registry.get_task_spec(task_id)
            manifest = self.recovery_store.manifest(task_id)
            try:
                connections = restore_recovery_connections(manifest["connections"], config.to_dict())
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
            spec, status = self._registry.create_task_spec(
                task_type="pipeline", task_source=f"resume:{task_id}",
                session_id=session_id, input_asset_id=input_asset_id,
                companion_asset_ids=companion_asset_ids,
                execution_profile=deepcopy(previous.execution_profile),
                priority=previous.priority, retry_of_task_id=task_id)
            manifest = deepcopy(manifest)
            manifest["resume_of_task_id"] = task_id
            try:
                self._state_store.save_task(spec, status, recovery_manifest=manifest)
            except Exception as exc:
                self._registry.discard_task(spec.task_id)
                raise AppExecutionError("failed to persist resumed task") from exc
            self._connection_snapshots[spec.task_id] = connections
            self._connection_records[spec.task_id] = deepcopy(manifest["connections"])
            return status

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
            return self._guard_locked(task_id, fn)

    def _guard_locked(self, task_id: str, fn):
        """Apply one lifecycle mutation while ``self._lock`` is already held."""
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
                    "speech.generate",
                    lambda spec, context: _lazy_speech_executor(spec, context),
                )
                _dispatcher.register_executor(
                    "speech.reference_analyze",
                    lambda spec, context: _lazy_reference_analysis_executor(spec, context),
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


def _lazy_speech_executor(task_spec, context):
    from .speech_service import get_speech_service

    return get_speech_service()._execute(task_spec, context)


def _lazy_reference_analysis_executor(task_spec, context):
    from .speech_service import get_speech_service

    return get_speech_service()._execute_reference_analysis(task_spec, context)
