"""Task routes."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.http.dependencies import artifact_service, task_service
from src.api.http.schemas.tasks import (
    ArtifactRecordResponse,
    ReviewNoteUpdateRequest,
    ReviewUpdateRequest,
    TaskBatchCreateRequest,
    TaskBatchCreateResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskArtifactsResponse,
    TaskListResponse,
    TaskPreviewResponse,
    TaskQueueSnapshotResponse,
    TaskQueueStatsResponse,
    TaskResultResponse,
    TaskSpecResponse,
    TaskStatusResponse,
)
from src.app.dto import TaskStatus
from src.app.services import ArtifactService, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])
queue_router = APIRouter(tags=["tasks"])


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse)
def cancel_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    task = svc.cancel_task(task_id)
    return TaskStatusResponse.from_task_status(task)


@router.post("/{task_id}/retry", response_model=TaskStatusResponse)
def retry_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    task = svc.retry_task(task_id)
    return TaskStatusResponse.from_task_status(task)


@router.patch("/{task_id}/review", response_model=TaskStatusResponse)
def set_review_state(
    task_id: str,
    body: ReviewUpdateRequest,
    svc: TaskService = Depends(task_service),
):
    task = svc.set_review_state(task_id, body.review_state)
    return TaskStatusResponse.from_task_status(task)


@router.post("/{task_id}/review-status", response_model=TaskStatusResponse)
def set_review_status(
    task_id: str,
    body: ReviewUpdateRequest,
    svc: TaskService = Depends(task_service),
):
    task = svc.set_review_state(task_id, body.review_state)
    return TaskStatusResponse.from_task_status(task)


@router.put("/{task_id}/review-note", response_model=TaskStatusResponse)
def set_review_note(
    task_id: str,
    body: ReviewNoteUpdateRequest,
    svc: TaskService = Depends(task_service),
):
    task = svc.set_review_note(task_id, body.review_note)
    return TaskStatusResponse.from_task_status(task)


@router.post("/{task_id}/review-note", response_model=TaskStatusResponse)
def post_review_note(
    task_id: str,
    body: ReviewNoteUpdateRequest,
    svc: TaskService = Depends(task_service),
):
    task = svc.set_review_note(task_id, body.review_note)
    return TaskStatusResponse.from_task_status(task)


@router.post("", response_model=TaskCreateResponse)
def create_task(
    body: TaskCreateRequest,
    svc: TaskService = Depends(task_service),
):
    spec, task = svc.create_task_spec(
        task_type=body.task_type,
        task_source=body.task_source,
        session_id=body.session_id,
        input_asset_id=body.input_asset_id,
        companion_asset_ids=body.companion_asset_ids,
        execution_profile=body.execution_profile,
        priority=body.priority,
        dedupe_key=body.dedupe_key,
    )
    return TaskCreateResponse(
        task=TaskStatusResponse.from_task_status(task),
        spec=TaskSpecResponse.from_task_spec(spec),
    )


@router.post("/batch", response_model=TaskBatchCreateResponse)
def create_tasks_batch(
    body: TaskBatchCreateRequest,
    svc: TaskService = Depends(task_service),
):
    items = []
    for item in body.items:
        spec, task = svc.create_task_spec(
            task_type=item.task_type,
            task_source=item.task_source,
            session_id=item.session_id,
            input_asset_id=item.input_asset_id,
            companion_asset_ids=item.companion_asset_ids,
            execution_profile=item.execution_profile,
            priority=item.priority,
            dedupe_key=item.dedupe_key,
        )
        items.append(
            TaskCreateResponse(
                task=TaskStatusResponse.from_task_status(task),
                spec=TaskSpecResponse.from_task_spec(spec),
            )
        )
    return TaskBatchCreateResponse(items=items)


@router.get("/running-count")
def get_running_count(
    svc: TaskService = Depends(task_service),
):
    return {"running": svc.running_count(), "can_start": svc.can_start()}


@router.get("/queue", response_model=TaskQueueSnapshotResponse)
@queue_router.get("/task-queue", response_model=TaskQueueSnapshotResponse)
def get_task_queue(
    svc: TaskService = Depends(task_service),
):
    snapshot = svc.get_queue_snapshot()
    return TaskQueueSnapshotResponse(
        queued_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["queued_tasks"]],
        running_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["running_tasks"]],
        completed_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["completed_tasks"]],
        failed_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["failed_tasks"]],
        cancelled_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["cancelled_tasks"]],
        skipped_tasks=[TaskStatusResponse.from_task_status(task) for task in snapshot["skipped_tasks"]],
        queue_stats=TaskQueueStatsResponse(**snapshot["queue_stats"]),
    )


@router.get("", response_model=TaskListResponse)
def list_tasks(
    state: str | None = Query(None, description="Filter by task state"),
    svc: TaskService = Depends(task_service),
):
    tasks = svc.list_tasks(state=state)
    return TaskListResponse.from_tasks(tasks)


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    task = svc.get_task(task_id)
    return TaskStatusResponse.from_task_status(task)


@router.get("/{task_id}/events")
def stream_task_events(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    """SSE endpoint that streams task status updates until terminal state."""
    _TERMINAL = frozenset({"completed", "failed", "cancelled", "skipped"})

    def _event_stream():
        last_state = ""
        last_progress = -1.0
        try:
            while True:
                task = svc.get_task(task_id)
                changed = task.state != last_state or abs(task.progress - last_progress) > 0.001
                if changed:
                    payload = TaskStatusResponse.from_task_status(task).model_dump_json()
                    yield f"data: {payload}\n\n"
                    last_state = task.state
                    last_progress = task.progress
                if task.state in _TERMINAL:
                    yield "event: done\ndata: {}\n\n"
                    return
                time.sleep(0.5)
        except Exception:
            yield "event: error\ndata: {}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{task_id}/spec", response_model=TaskSpecResponse)
def get_task_spec(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    spec = svc.get_task_spec(task_id)
    return TaskSpecResponse.from_task_spec(spec)


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
def get_task_artifacts(
    task_id: str,
    task_svc: TaskService = Depends(task_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    task = task_svc.get_task(task_id)
    artifact_set = artifact_svc.get_task_artifacts(task.task_id)
    return TaskArtifactsResponse(
        task_id=task.task_id,
        files=dict(artifact_set.files),
        primary_output=artifact_set.primary_output,
        entries=[
            ArtifactRecordResponse(
                artifact_id=entry.artifact_id,
                task_id=entry.task_id,
                artifact_type=entry.artifact_type,
                path=entry.path,
                label=entry.label,
                preview_kind=entry.preview_kind,
                stage=entry.stage,
                is_primary=entry.is_primary,
                metadata=dict(entry.metadata),
            )
            for entry in artifact_set.entries
        ],
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
def get_task_result(
    task_id: str,
    task_svc: TaskService = Depends(task_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    task = task_svc.get_task(task_id)
    result_view = artifact_svc.get_task_result_view(task.task_id)
    primary_output = result_view["primary_output"]
    secondary_outputs = result_view["secondary_outputs"]
    return TaskResultResponse(
        task=TaskStatusResponse.from_task_status(task),
        primary_output=(
            ArtifactRecordResponse(
                artifact_id=primary_output.artifact_id,
                task_id=primary_output.task_id,
                artifact_type=primary_output.artifact_type,
                path=primary_output.path,
                label=primary_output.label,
                preview_kind=primary_output.preview_kind,
                stage=primary_output.stage,
                is_primary=primary_output.is_primary,
                metadata=dict(primary_output.metadata),
            )
            if primary_output is not None
            else None
        ),
        secondary_outputs=[
            ArtifactRecordResponse(
                artifact_id=entry.artifact_id,
                task_id=entry.task_id,
                artifact_type=entry.artifact_type,
                path=entry.path,
                label=entry.label,
                preview_kind=entry.preview_kind,
                stage=entry.stage,
                is_primary=entry.is_primary,
                metadata=dict(entry.metadata),
            )
            for entry in secondary_outputs
        ],
        warnings=list(result_view["warnings"]),
    )


@router.get("/{task_id}/preview", response_model=TaskPreviewResponse)
def get_task_preview(
    task_id: str,
    task_svc: TaskService = Depends(task_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    task = task_svc.get_task(task_id)
    preview_view = artifact_svc.get_task_preview_view(task.task_id)
    primary_output = preview_view["primary_output"]
    secondary_outputs = preview_view["secondary_outputs"]
    return TaskPreviewResponse(
        task=TaskStatusResponse.from_task_status(task),
        primary_output=(
            ArtifactRecordResponse(
                artifact_id=primary_output.artifact_id,
                task_id=primary_output.task_id,
                artifact_type=primary_output.artifact_type,
                path=primary_output.path,
                label=primary_output.label,
                preview_kind=primary_output.preview_kind,
                stage=primary_output.stage,
                is_primary=primary_output.is_primary,
                metadata=dict(primary_output.metadata),
            )
            if primary_output is not None
            else None
        ),
        secondary_outputs=[
            ArtifactRecordResponse(
                artifact_id=entry.artifact_id,
                task_id=entry.task_id,
                artifact_type=entry.artifact_type,
                path=entry.path,
                label=entry.label,
                preview_kind=entry.preview_kind,
                stage=entry.stage,
                is_primary=entry.is_primary,
                metadata=dict(entry.metadata),
            )
            for entry in secondary_outputs
        ],
        warnings=list(preview_view["warnings"]),
        preview_modes=list(preview_view["preview_modes"]),
        artifact_count=preview_view["artifact_count"],
    )
