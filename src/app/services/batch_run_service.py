"""Persistent BatchRun coordination over ordinary Pipeline tasks."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
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
        self._llm_snapshots: dict[str, dict] = {}
        self._graph_snapshots: dict[str, dict] = {}
        self._input_identities: dict[str, dict] = {}
        self._legacy_retry_tasks: dict[str, dict[str, str]] = {}
        self._restored_batch_ids: set[str] = set()
        self._retry_validation_errors: dict[str, dict[str, str]] = {}
        self._retry_identity_cache: dict[tuple[str, str], tuple] = {}

        if self._state_store is not None:
            for record in self._state_store.load_batch_runs():
                self._restored_batch_ids.add(record.batch_id)
                self._restore_record(record)
                self._batches[record.batch_id] = record

    def discover_audio_files(
        self,
        directory: str,
        *,
        recursive: bool = True,
        limit: int | None = None,
        media_kind: str = "audio",
    ) -> list[dict[str, Any]]:
        root = Path(directory).expanduser()
        if not root.exists():
            raise AppValidationError(f"input directory does not exist: {directory}")
        if not root.is_dir():
            raise AppValidationError(f"input path is not a directory: {directory}")

        if media_kind not in {"audio", "subtitle", "all"}:
            raise AppValidationError("media_kind must be audio, subtitle or all")
        extensions = (set(AUDIO_EXTENSIONS) if media_kind == "audio" else set(SUBTITLE_EXTENSIONS)
                      if media_kind == "subtitle" else set(AUDIO_EXTENSIONS) | set(SUBTITLE_EXTENSIONS))
        iterator = root.rglob("*") if recursive else root.glob("*")
        paths = sorted(
            (
                path.resolve()
                for path in iterator
                if path.is_file() and path.suffix.lower() in extensions
            ),
            key=lambda path: str(path).casefold(),
        )
        if limit is not None:
            paths = paths[:limit]
        return [
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "kind": "audio" if path.suffix.lower() in AUDIO_EXTENSIONS else "subtitle",
                "companion_paths": self._discover_companions(path) if path.suffix.lower() in AUDIO_EXTENSIONS else [],
                "companion_subtitles": self._subtitle_summaries(path),
            }
            for path in paths
        ]

    def create_batch(
        self,
        *,
        name: str,
        inputs: list[dict[str, Any]] | None = None,
        output_dir: str,
        execution_profile: dict[str, Any],
        max_parallel: int = 1,
        groups: list[dict[str, Any]] | None = None,
        client_request_id: str | None = None,
    ) -> BatchRunRecord:
        if execution_profile.get("version") == 2:
            return self._create_graph_batch(name=name, inputs=inputs or [], groups=groups or [],
                output_dir=output_dir, execution_profile=execution_profile, max_parallel=max_parallel,
                client_request_id=client_request_id)
        if groups:
            raise AppValidationError("version 1 batches do not accept graph groups")
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
        execution_profile = deepcopy(execution_profile)
        translation = execution_profile["stages"].get("translate", {})
        from src.core.subtitles.translation_reuse import prepare_translation_profile
        try:
            needs_translation = any(prepare_translation_profile(execution_profile, path, companions)
                .get("stages", {}).get("translate", {}).get("enabled", True)
                for path, companions in resolved_inputs)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        if not needs_translation and translation.get("enabled", True):
            # Freeze the no-translation decision for delayed children too.
            translation["enabled"] = False
            translation.setdefault("options", {}).update(reuse_only=True, reuse_unverified=False)
        selected_settings = None
        if needs_translation and "connection_ref" in translation.get("options", {}):
            from src.config import config
            from src.task_connection_context import resolve_task_settings, capture_connections
            from src.recovery_connections import capture_recovery_connections
            try:
                selected_settings = resolve_task_settings(config.to_dict(), execution_profile)
                execution_profile["llm_connection_record"] = capture_recovery_connections(
                    selected_settings, capture_connections(selected_settings), include_tts=False)
            except ValueError as exc:
                can_attempt_reuse = all(not prepare_translation_profile(execution_profile, path, companions,
                    allow_unverified=True).get("stages", {}).get("translate", {}).get("enabled", True)
                    for path, companions in resolved_inputs)
                if not can_attempt_reuse:
                    raise AppValidationError(str(exc)) from exc
                selected_settings = None
                translation["enabled"] = False
                translation.setdefault("options", {}).update(reuse_only=True, reuse_unverified=True)
            if selected_settings is not None and translation.get("model") in (None, "", "default"):
                translation["model"] = selected_settings["api"][f"{translation['provider']}_model"]
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
            from ..persistence.recovery_store import file_identity
            self._input_identities[batch_id] = {
                item.item_id: {path: file_identity(path) for path in [item.input_path, *item.companion_paths]}
                for item in record.items}
            if selected_settings is not None:
                self._llm_snapshots[batch_id] = {key: deepcopy(selected_settings.get(key, {}))
                    for key in ("api", "connection_profiles")}
            self._batches[batch_id] = record
            self._cancel_events[batch_id] = threading.Event()
            self._save_locked(record)
            self._start_monitor_locked(batch_id)
            return deepcopy(record)

    def _create_graph_batch(self, *, name, inputs, groups, output_dir, execution_profile,
                            max_parallel, client_request_id) -> BatchRunRecord:
        from .graph_pipeline_service import (FrozenGraphSubmission, capture_graph_speech_connections,
            freeze_graph_connections, freeze_graph_speech, prepare_graph_profile)
        from src.core.orchestration.pipeline.graph_validation import validate_graph_profile

        if inputs or not 1 <= len(groups) <= 500:
            raise AppValidationError("graph batches require 1 to 500 explicit groups and no legacy inputs")
        if not 1 <= max_parallel <= 4:
            raise AppValidationError("max_parallel must be between 1 and 4")
        if set(execution_profile) != {"version", "graph"}:
            raise AppValidationError("graph batch profile accepts only version and graph")
        if client_request_id is not None and (not isinstance(client_request_id, str)
                or not client_request_id.strip() or len(client_request_id) > 100):
            raise AppValidationError("client_request_id must contain 1 to 100 characters")
        fingerprint = hashlib.sha256(json.dumps({"name": name, "groups": groups,
            "output_dir": output_dir, "execution_profile": execution_profile,
            "max_parallel": max_parallel}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            existing = self._idempotent_record_locked(client_request_id, fingerprint)
            if existing:
                return deepcopy(existing)

        prepared_groups, group_ids = [], set()
        for group in groups:
            group_id = group.get("group_id")
            if not isinstance(group_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", group_id):
                raise AppValidationError("each group needs a valid stable group_id")
            if group_id in group_ids:
                raise AppValidationError(f"duplicate group_id: {group_id}")
            group_ids.add(group_id)
            if set(group) - {"group_id", "label", "bindings"}:
                raise AppValidationError(f"group {group_id}: unsupported fields; parameters belong to the shared graph")
            label = group.get("label", "")
            if not isinstance(label, str) or len(label) > 100:
                raise AppValidationError(f"group {group_id}: label must contain at most 100 characters")
            try:
                profile = validate_graph_profile({**deepcopy(execution_profile), "bindings": group.get("bindings", {})})
                profile, _ = prepare_graph_profile(profile)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                raise AppValidationError(f"group {group_id}: {exc}") from exc
            prepared_groups.append((group, profile))

        # Resolve shared selections once, after every material group validates.
        try:
            shared = freeze_graph_speech(prepared_groups[0][1])
            shared, connections = freeze_graph_connections(shared)
            speech_connections = capture_graph_speech_connections(shared)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise AppValidationError(str(exc)) from exc
        snapshots, items = {}, []
        for group, profile in prepared_groups:
            profile["graph"] = deepcopy(shared["graph"])
            profile["_graph_runtime"].update(
                node_snapshots=deepcopy(shared["_graph_runtime"]["node_snapshots"]), connections_frozen=True)
            frozen = FrozenGraphSubmission(profile, deepcopy(connections), deepcopy(speech_connections))
            item_id = group["group_id"]
            snapshots[item_id] = frozen
            items.append(BatchRunItem(item_id=item_id, group_id=item_id, label=group.get("label", ""),
                input_path=frozen.paths[0], companion_paths=frozen.paths[1:], bindings=deepcopy(profile["bindings"])))
        self._pipeline_orchestrator.validate_frozen_graph_resources(next(iter(snapshots.values())))

        created_at, batch_id = _now(), f"batch-{uuid4().hex[:12]}"
        record = BatchRunRecord(batch_id=batch_id, name=name.strip() or f"Batch {created_at[:16]}",
            state="pending", progress=0.0, created_at=created_at, updated_at=created_at, finished_at=None,
            output_dir=str(Path(output_dir).expanduser().resolve()) if output_dir else "",
            execution_profile={"version": 2, "graph": deepcopy(shared["graph"])},
            max_parallel=max_parallel, items=items, client_request_id=client_request_id,
            request_fingerprint=fingerprint)
        with self._lock:
            existing = self._idempotent_record_locked(client_request_id, fingerprint)
            if existing:
                return deepcopy(existing)
            # Persist acceptance before publishing to memory or launching the monitor.
            self._save_locked(record)
            self._graph_snapshots[batch_id] = snapshots
            self._batches[batch_id] = record
            self._cancel_events[batch_id] = threading.Event()
            self._annotate_retry_locked(record)
            self._start_monitor_locked(batch_id)
            return deepcopy(record)

    def _idempotent_record_locked(self, request_id: str | None, fingerprint: str):
        if request_id is None:
            return None
        for record in self._batches.values():
            if record.client_request_id == request_id:
                if record.request_fingerprint != fingerprint:
                    raise AppValidationError("client_request_id already belongs to a different submission")
                self._annotate_retry_locked(record)
                return record
        return None

    def list_batches(self) -> list[BatchRunRecord]:
        with self._lock:
            for record in self._batches.values():
                if self._refresh_record_locked(record):
                    self._save_locked(record)
                self._annotate_retry_locked(record)
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
            self._annotate_retry_locked(record)
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

            self._annotate_retry_locked(record)
            if record.retry_blocked_reason:
                raise AppValidationError(record.retry_blocked_reason)
            # Validate every candidate before resetting any group or admitting a task.
            for item in retry_items:
                try:
                    if record.execution_profile.get("version") == 2:
                        from .graph_pipeline_service import validate_frozen_graph_submission
                        validate_frozen_graph_submission(self._graph_snapshots[batch_id][item.item_id])
                    else:
                        self._validate_legacy_identities(record, item)
                        self._pipeline_orchestrator.validate_retry_task(item.current_task_id)
                except (ValueError, KeyError, OSError, TypeError, AppValidationError) as exc:
                    reason = f"group {item.group_id or item.item_id}: {exc}; submit a new batch"
                    self._retry_validation_errors.setdefault(batch_id, {})[item.item_id] = reason
                    self._annotate_retry_locked(record)
                    self._save_locked(record)
                    raise AppValidationError(reason) from exc

            for item in retry_items:
                if record.execution_profile.get("version") != 2:
                    self._legacy_retry_tasks.setdefault(batch_id, {})[item.item_id] = item.current_task_id
                item.current_task_id = None
                item.state = "pending"
                item.progress = 0.0
                item.message = "queued for batch retry"
                item.output_path = ""
                item.error = None
                item.retry_blocked_reason = None
            record.state = "pending"
            record.progress = self._aggregate_progress(record)
            record.updated_at = _now()
            record.finished_at = None
            record.retry_blocked_reason = None
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
            if record.execution_profile.get("version") == 2:
                from .graph_pipeline_service import validate_frozen_graph_submission
                frozen = self._graph_snapshots.get(record.batch_id, {}).get(item.item_id)
                validate_frozen_graph_submission(frozen)
                task = self._pipeline_orchestrator.submit_frozen_graph(frozen,
                    output_dir=record.output_dir, task_source=f"batch-run:{record.batch_id}")
            elif item.item_id in self._legacy_retry_tasks.get(record.batch_id, {}):
                self._validate_legacy_identities(record, item)
                previous = self._legacy_retry_tasks[record.batch_id].pop(item.item_id)
                task = self._pipeline_orchestrator.retry_task(previous, _batch_managed=True)
            else:
                task = self._submit_legacy_item(record, item)
            item.current_task_id = task.task_id
            item.task_ids.append(task.task_id)
            item.state = task.state
            item.progress = task.progress
            item.message = task.message
            item.error = deepcopy(task.error)
            if task.state == "completed" and task.detail:
                item.output_path = task.detail
        except Exception as exc:
            item.state = "failed"
            item.progress = 1.0
            item.message = "batch item submission failed"
            item.error = {
                "code": "BATCH_ITEM_SUBMISSION_FAILED",
                "stage": "prepare",
                "message": str(exc),
                "retryable": not isinstance(exc, (ValueError, AppValidationError, OSError)),
                "detail": str(exc),
            }

    def _submit_legacy_item(self, record: BatchRunRecord, item: BatchRunItem):
        """Retain legacy initial submissions; retries use the original child snapshot."""
        self._validate_legacy_identities(record, item)
        from src.task_connection_context import connection_context
        snapshot = self._llm_snapshots.get(record.batch_id)
        if snapshot is None and record.execution_profile.get("llm_connection_record"):
            raise AppValidationError("original translation snapshot unavailable; submit a new batch")
        with connection_context(snapshot):
            return self._pipeline_orchestrator.submit_task(
                PipelineRequest(input_path=item.input_path, output_dir=record.output_dir,
                    companion_paths=list(item.companion_paths), execution_profile=deepcopy(record.execution_profile)),
                task_source=f"batch-run:{record.batch_id}")

    def _validate_legacy_identities(self, record: BatchRunRecord, item: BatchRunItem) -> None:
        from ..persistence.recovery_store import file_identity
        original = self._input_identities.get(record.batch_id, {}).get(item.item_id)
        if not original:
            raise AppValidationError("original material identities unavailable; submit a new batch")
        if any(file_identity(path) != fact for path, fact in original.items()):
            raise AppValidationError("input materials changed since submission; submit a new batch")

    def _annotate_retry_locked(self, record: BatchRunRecord) -> None:
        candidates = [item for item in record.items if item.state in {"failed", "cancelled"}]
        active = record.state not in BATCH_TERMINAL_STATES
        for item in record.items:
            reason = None
            if item.state not in {"failed", "cancelled"}:
                reason = "only failed or cancelled groups can be retried"
            elif active:
                reason = "batch run is still active"
            elif record.batch_id in self._restored_batch_ids:
                reason = "original private snapshots unavailable after restart; submit a new batch"
            elif (item.error or {}).get("result_unknown"):
                reason = "remote result is unknown; verify the provider outcome before a new submission"
            elif (item.error or {}).get("code") == "BATCH_CHILD_TASK_UNAVAILABLE":
                reason = "original child task outcome unavailable; submit a new batch after checking its outcome"
            elif (item.error or {}).get("retryable") is False:
                reason = (item.error or {}).get("message") or "group cannot be retried; submit a new batch"
            elif record.execution_profile.get("version") == 2:
                reason = self._graph_retry_reason(record, item)
            elif not item.current_task_id:
                reason = "unsubmitted legacy item has no frozen child snapshot; submit a new batch"
            reason = self._retry_validation_errors.get(record.batch_id, {}).get(item.item_id, reason)
            item.retry_blocked_reason = reason
        record.retry_blocked_reason = ("batch run is still active" if active else
            next((item.retry_blocked_reason for item in candidates if item.retry_blocked_reason), None)
            if candidates else "batch run has no failed or cancelled groups")

    def _graph_retry_reason(self, record: BatchRunRecord, item: BatchRunItem) -> str | None:
        """Keep polling cheap; retry itself always repeats full identity validation."""
        from .graph_pipeline_service import (capture_graph_speech_connections,
                                             validate_frozen_graph_submission)
        frozen = self._graph_snapshots.get(record.batch_id, {}).get(item.item_id)
        if frozen is None:
            return "original frozen graph unavailable; submit a new batch"
        try:
            states = []
            for path in frozen.paths:
                stat = Path(path).stat()
                states.append((path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
            key, states = (record.batch_id, item.item_id), tuple(states)
            if self._retry_identity_cache.get(key) != states:
                validate_frozen_graph_submission(frozen)
                self._retry_identity_cache[key] = states
            elif capture_graph_speech_connections(frozen.profile) != frozen.speech_connections:
                raise ValueError("frozen speech credentials changed; submit a new batch")
        except (ValueError, KeyError, OSError, TypeError) as exc:
            return f"group {item.group_id or item.item_id}: {exc}; submit a new batch"
        return None

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
        if self._all_items_terminal(record):
            if record.state == "cancelling":
                record.state = "cancelled"
            elif any(
                item.state in {"failed", "cancelled"} for item in record.items
            ):
                record.state = "completed_with_errors"
            else:
                record.state = "completed"
            record.progress = 1.0
            record.updated_at = _now()
            record.finished_at = record.finished_at or record.updated_at
            self._state_store.save_batch_run(record)
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
        self._annotate_retry_locked(record)
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
        from src.core.subtitles.companions import discover_subtitles
        return [str(candidate.resolve()) for candidate in discover_subtitles(path)]

    @staticmethod
    def _subtitle_summaries(path: Path) -> list[dict]:
        from src.core.subtitles.companions import subtitle_summary
        if path.suffix.lower() in SUBTITLE_EXTENSIONS:
            return [subtitle_summary(str(path))]
        return [subtitle_summary(candidate) for candidate in BatchRunService._discover_companions(path)]


_service: BatchRunService | None = None
_lock = threading.Lock()


def get_batch_run_service() -> BatchRunService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = BatchRunService(state_store=get_state_store())
    return _service
