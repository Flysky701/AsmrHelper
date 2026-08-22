"""Persistent BatchRun coordination over ordinary Pipeline tasks."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from src.core.batches import BatchRunItem, BatchRunRecord
from src.utils.constants import AUDIO_EXTENSIONS

from ..dto import PipelineRequest
from ..errors import AppValidationError
from ..persistence import SqliteStateStore, get_state_store
from .pipeline_task_orchestrator import (
    PipelineTaskOrchestrator,
    get_pipeline_task_orchestrator,
)


ITEM_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "skipped"})
BATCH_TERMINAL_STATES = frozenset(
    {"completed", "completed_with_errors", "cancelled", "interrupted"}
)
SUBTITLE_EXTENSIONS = (".vtt", ".srt", ".lrc")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BatchRunService:
    """Own batch identity, child-task membership, aggregation and controls."""

    def __init__(
        self,
        pipeline_orchestrator: PipelineTaskOrchestrator | None = None,
        state_store: SqliteStateStore | None = None,
    ) -> None:
        self._pipeline_orchestrator = (
            pipeline_orchestrator or get_pipeline_task_orchestrator()
        )
        self._state_store = state_store
        self._lock = threading.RLock()
        self._batches: dict[str, BatchRunRecord] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_events: dict[str, threading.Event] = {}

        if self._state_store is not None:
            for record in self._state_store.load_batch_runs():
                self._restore_record(record)
                self._batches[record.batch_id] = record

    def discover_audio_files(
        self,
        directory: str,
        *,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        root = Path(directory).expanduser()
        if not root.exists():
            raise AppValidationError(f"input directory does not exist: {directory}")
        if not root.is_dir():
            raise AppValidationError(f"input path is not a directory: {directory}")

        iterator = root.rglob("*") if recursive else root.glob("*")
        paths = sorted(
            (
                path.resolve()
                for path in iterator
                if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        return [
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "companion_paths": self._discover_companions(path),
            }
            for path in paths
        ]

    def create_batch(
        self,
        *,
        name: str,
        inputs: list[dict[str, Any]],
        output_dir: str,
        execution_profile: dict[str, Any],
        max_parallel: int = 1,
    ) -> BatchRunRecord:
        if not inputs:
            raise AppValidationError("batch run requires at least one input")
        if len(inputs) > 500:
            raise AppValidationError("batch run accepts at most 500 inputs")
        if execution_profile.get("version") != 1 or not isinstance(
            execution_profile.get("stages"), dict
        ):
            raise AppValidationError(
                "batch execution profile must use StageProfile version 1"
            )
        if not 1 <= max_parallel <= 4:
            raise AppValidationError("max_parallel must be between 1 and 4")

        resolved_inputs: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        for entry in inputs:
            source = Path(str(entry.get("path") or "")).expanduser()
            if not source.exists() or not source.is_file():
                raise AppValidationError(f"input file does not exist: {source}")
            if source.suffix.lower() not in AUDIO_EXTENSIONS:
                raise AppValidationError(f"unsupported audio input: {source}")
            source = source.resolve()
            key = str(source).casefold()
            if key in seen:
                continue
            seen.add(key)

            companion_paths: list[str] = []
            for raw_companion in entry.get("companion_paths") or []:
                companion = Path(str(raw_companion)).expanduser()
                if not companion.exists() or not companion.is_file():
                    raise AppValidationError(
                        f"companion file does not exist: {companion}"
                    )
                companion_paths.append(str(companion.resolve()))
            resolved_inputs.append((str(source), companion_paths))

        if not resolved_inputs:
            raise AppValidationError("batch run has no unique inputs")

        created_at = _now()
        batch_id = f"batch-{uuid4().hex[:12]}"
        record = BatchRunRecord(
            batch_id=batch_id,
            name=name.strip() or f"批量任务 {created_at[:16]}",
            state="pending",
            progress=0.0,
            created_at=created_at,
            updated_at=created_at,
            finished_at=None,
            output_dir=str(Path(output_dir).expanduser().resolve()) if output_dir else "",
            execution_profile=deepcopy(execution_profile),
            max_parallel=max_parallel,
            items=[
                BatchRunItem(
                    item_id=f"item-{index}",
                    input_path=input_path,
                    companion_paths=companion_paths,
                )
                for index, (input_path, companion_paths) in enumerate(
                    resolved_inputs, start=1
                )
            ],
        )

        with self._lock:
            self._batches[batch_id] = record
            self._cancel_events[batch_id] = threading.Event()
            self._save_locked(record)
            self._start_monitor_locked(batch_id)
            return deepcopy(record)

    def list_batches(self) -> list[BatchRunRecord]:
        with self._lock:
            for record in self._batches.values():
                if self._refresh_record_locked(record):
                    self._save_locked(record)
            return sorted(
                (deepcopy(record) for record in self._batches.values()),
                key=lambda record: (record.created_at, record.batch_id),
                reverse=True,
            )

    def get_batch(self, batch_id: str) -> BatchRunRecord:
        with self._lock:
            record = self._require_locked(batch_id)
            if self._refresh_record_locked(record):
                self._save_locked(record)
            return deepcopy(record)

    def request_cancel(self, batch_id: str) -> BatchRunRecord:
        with self._lock:
            record = self._require_locked(batch_id)
            if record.state in BATCH_TERMINAL_STATES:
                raise AppValidationError(
                    f"cannot cancel batch run in state: {record.state}"
                )
            record.state = "cancelling"
            record.updated_at = _now()
            event = self._cancel_events.setdefault(batch_id, threading.Event())
            event.set()
            self._save_locked(record)
            self._start_monitor_locked(batch_id)
            return deepcopy(record)

    def retry_failed(self, batch_id: str) -> BatchRunRecord:
        with self._lock:
            record = self._require_locked(batch_id)
            thread = self._threads.get(batch_id)
            if thread is not None and thread.is_alive():
                raise AppValidationError("batch run is still active")

            retry_items = [
                item
                for item in record.items
                if item.state in {"failed", "cancelled"}
            ]
            if not retry_items:
                raise AppValidationError("batch run has no failed items to retry")

            for item in retry_items:
                item.current_task_id = None
                item.state = "pending"
                item.progress = 0.0
                item.message = "queued for batch retry"
                item.output_path = ""
                item.error = None
            record.state = "pending"
            record.progress = self._aggregate_progress(record)
            record.updated_at = _now()
            record.finished_at = None
            self._cancel_events[batch_id] = threading.Event()
            self._save_locked(record)
            self._start_monitor_locked(batch_id)
            return deepcopy(record)

    def _run_batch(self, batch_id: str) -> None:
        while True:
            with self._lock:
                record = self._batches.get(batch_id)
                if record is None:
                    return
                cancel_event = self._cancel_events.setdefault(
                    batch_id, threading.Event()
                )
                changed = self._refresh_record_locked(record)

                if cancel_event.is_set():
                    changed = self._cancel_items_locked(record) or changed
                else:
                    active = sum(
                        item.state in {"pending", "running"}
                        and item.current_task_id is not None
                        for item in record.items
                    )
                    launchable = [
                        item
                        for item in record.items
                        if item.state == "pending" and item.current_task_id is None
                    ]
                    for item in launchable[: max(0, record.max_parallel - active)]:
                        self._launch_item_locked(record, item)
                        changed = True

                if self._all_items_terminal(record):
                    if cancel_event.is_set():
                        record.state = "cancelled"
                    elif any(item.state == "failed" for item in record.items):
                        record.state = "completed_with_errors"
                    elif any(item.state == "cancelled" for item in record.items):
                        record.state = "completed_with_errors"
                    else:
                        record.state = "completed"
                    record.progress = 1.0
                    record.finished_at = record.finished_at or _now()
                    record.updated_at = _now()
                    self._save_locked(record)
                    return

                next_state = "cancelling" if cancel_event.is_set() else "running"
                if record.state != next_state:
                    record.state = next_state
                    changed = True
                aggregate = self._aggregate_progress(record)
                if aggregate != record.progress:
                    record.progress = aggregate
                    changed = True
                if changed:
                    record.updated_at = _now()
                    self._save_locked(record)

            cancel_event.wait(0.75)

    def _launch_item_locked(
        self,
        record: BatchRunRecord,
        item: BatchRunItem,
    ) -> None:
        try:
            task = self._pipeline_orchestrator.submit_task(
                PipelineRequest(
                    input_path=item.input_path,
                    output_dir=record.output_dir,
                    companion_paths=list(item.companion_paths),
                    execution_profile=deepcopy(record.execution_profile),
                ),
                task_source=f"batch-run:{record.batch_id}",
            )
            item.current_task_id = task.task_id
            item.task_ids.append(task.task_id)
            item.state = task.state
            item.progress = task.progress
            item.message = task.message
            item.error = deepcopy(task.error)
        except Exception as exc:
            item.state = "failed"
            item.progress = 1.0
            item.message = "batch item submission failed"
            item.error = {
                "code": "BATCH_ITEM_SUBMISSION_FAILED",
                "stage": "prepare",
                "message": str(exc),
                "retryable": True,
                "detail": str(exc),
            }

    def _cancel_items_locked(self, record: BatchRunRecord) -> bool:
        changed = False
        for item in record.items:
            if item.state == "pending" and item.current_task_id is None:
                item.state = "cancelled"
                item.progress = 1.0
                item.message = "cancelled before submission"
                changed = True
                continue
            if item.state not in {"pending", "running"} or not item.current_task_id:
                continue
            try:
                task = self._pipeline_orchestrator.request_cancel(item.current_task_id)
                item.state = task.state
                item.progress = task.progress
                item.message = task.message
            except Exception:
                changed = self._refresh_item_locked(item) or changed
            else:
                changed = True
        return changed

    def _refresh_record_locked(self, record: BatchRunRecord) -> bool:
        changed = False
        for item in record.items:
            if item.current_task_id and item.state not in ITEM_TERMINAL_STATES:
                changed = self._refresh_item_locked(item) or changed
        aggregate = self._aggregate_progress(record)
        if aggregate != record.progress:
            record.progress = aggregate
            changed = True
        if changed:
            record.updated_at = _now()
        return changed

    def _refresh_item_locked(self, item: BatchRunItem) -> bool:
        if not item.current_task_id:
            return False
        before = (
            item.state,
            item.progress,
            item.message,
            item.output_path,
            item.error,
        )
        try:
            task = self._pipeline_orchestrator.get_task(item.current_task_id)
        except Exception as exc:
            item.state = "failed"
            item.progress = 1.0
            item.message = "batch child task is unavailable"
            item.error = {
                "code": "BATCH_CHILD_TASK_UNAVAILABLE",
                "stage": "prepare",
                "message": str(exc),
                "retryable": True,
                "detail": str(exc),
            }
        else:
            item.state = task.state
            item.progress = min(1.0, max(0.0, float(task.progress)))
            item.message = task.message
            item.error = deepcopy(task.error)
            if task.state == "completed" and task.detail:
                item.output_path = task.detail
        after = (
            item.state,
            item.progress,
            item.message,
            item.output_path,
            item.error,
        )
        return after != before

    def _restore_record(self, record: BatchRunRecord) -> None:
        if record.state in BATCH_TERMINAL_STATES:
            return
        for item in record.items:
            if item.state not in ITEM_TERMINAL_STATES:
                item.state = "failed"
                item.progress = 1.0
                item.message = "batch execution was interrupted by application restart"
                item.error = {
                    "code": "BATCH_INTERRUPTED",
                    "stage": "prepare",
                    "message": item.message,
                    "retryable": True,
                    "detail": item.message,
                }
        record.state = "interrupted"
        record.progress = self._aggregate_progress(record)
        record.updated_at = _now()
        record.finished_at = record.finished_at or record.updated_at
        self._state_store.save_batch_run(record)

    def _start_monitor_locked(self, batch_id: str) -> None:
        current = self._threads.get(batch_id)
        if current is not None and current.is_alive():
            return
        thread = threading.Thread(
            target=self._run_batch,
            args=(batch_id,),
            name=f"batch-run-{batch_id}",
            daemon=True,
        )
        self._threads[batch_id] = thread
        thread.start()

    def _require_locked(self, batch_id: str) -> BatchRunRecord:
        try:
            return self._batches[batch_id]
        except KeyError as exc:
            raise AppValidationError(f"unknown batch id: {batch_id}") from exc

    def _save_locked(self, record: BatchRunRecord) -> None:
        if self._state_store is not None:
            self._state_store.save_batch_run(record)

    @staticmethod
    def _aggregate_progress(record: BatchRunRecord) -> float:
        if not record.items:
            return 0.0
        handled = sum(
            1.0 if item.state in ITEM_TERMINAL_STATES else item.progress
            for item in record.items
        )
        return round(handled / len(record.items), 6)

    @staticmethod
    def _all_items_terminal(record: BatchRunRecord) -> bool:
        return bool(record.items) and all(
            item.state in ITEM_TERMINAL_STATES for item in record.items
        )

    @staticmethod
    def _discover_companions(path: Path) -> list[str]:
        for suffix in SUBTITLE_EXTENSIONS:
            candidate = path.with_suffix(suffix)
            if candidate.exists() and candidate.is_file():
                return [str(candidate.resolve())]
        return []


_service: BatchRunService | None = None
_lock = threading.Lock()


def get_batch_run_service() -> BatchRunService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = BatchRunService(state_store=get_state_store())
    return _service
