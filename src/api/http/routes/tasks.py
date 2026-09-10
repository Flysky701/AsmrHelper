"""Task routes."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.api.http.dependencies import (
    artifact_service,
    pipeline_task_orchestrator,
    task_dispatcher,
    task_service,
)
from src.api.http.schemas.tasks import (
    ReviewNoteUpdateRequest,
    ReviewUpdateRequest,
    RuntimeEventResponse,
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
from src.app.errors import AppValidationError
from src.app.services import ArtifactService, PipelineTaskOrchestrator, TaskService
from src.core.tasks import TaskDispatcher

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/{task_id}/cancel", response_model=TaskStatusResponse)
def cancel_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
    pipeline_svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
    dispatcher: TaskDispatcher = Depends(task_dispatcher),
):
    current = svc.get_task(task_id)
    task = (
        pipeline_svc.request_cancel(task_id)
        if current.task_type == "pipeline"
        else dispatcher.request_cancel(task_id)
    )
    return TaskStatusResponse.from_task_status(task)


@router.post("/{task_id}/retry", response_model=TaskStatusResponse)
def retry_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
    pipeline_svc: PipelineTaskOrchestrator = Depends(pipeline_task_orchestrator),
    dispatcher: TaskDispatcher = Depends(task_dispatcher),
):
    current = svc.get_task(task_id)
    task = (
        pipeline_svc.retry_task(task_id)
        if current.task_type == "pipeline"
        else dispatcher.submit(svc.retry_task(task_id).task_id)
    )
    return TaskStatusResponse.from_task_status(task)


@router.patch("/{task_id}/review", response_model=TaskStatusResponse)
def set_review_state(
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


@router.post("", response_model=TaskCreateResponse)
def create_task(
    body: TaskCreateRequest,
    svc: TaskService = Depends(task_service),
    dispatcher: TaskDispatcher = Depends(task_dispatcher),
):
    if dispatcher.resolve_executor(body.task_type) is None:
        raise AppValidationError(
            f"no executable handler registered for task_type: {body.task_type}"
        )
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
    submitted = dispatcher.submit(task.task_id)
    return TaskCreateResponse(
        task=TaskStatusResponse.from_task_status(submitted),
        spec=TaskSpecResponse.from_task_spec(spec),
    )


@router.post("/batch", response_model=TaskBatchCreateResponse)
def create_tasks_batch(
    body: TaskBatchCreateRequest,
    svc: TaskService = Depends(task_service),
    dispatcher: TaskDispatcher = Depends(task_dispatcher),
):
    missing_handlers = sorted(
        {
            item.task_type
            for item in body.items
            if dispatcher.resolve_executor(item.task_type) is None
        }
    )
    if missing_handlers:
        raise AppValidationError(
            "no executable handler registered for task_type: "
            + ", ".join(missing_handlers)
        )
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
        submitted = dispatcher.submit(task.task_id)
        items.append(
            TaskCreateResponse(
                task=TaskStatusResponse.from_task_status(submitted),
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
    after_sequence: int = Query(0, ge=0),
    svc: TaskService = Depends(task_service),
):
    """Stream incremental runtime events while TaskStatus remains authoritative."""
    _TERMINAL = frozenset({"completed", "failed", "cancelled", "skipped"})

    def _event_stream():
        cursor = after_sequence
        try:
            while True:
                events = svc.list_events(task_id, after_sequence=cursor)
                for event in events:
                    payload = RuntimeEventResponse.from_runtime_event(
                        event
                    ).model_dump_json()
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: runtime\n"
                        f"data: {payload}\n\n"
                    )
                    cursor = event.sequence
                task = svc.get_task(task_id)
                if task.state in _TERMINAL:
                    payload = TaskStatusResponse.from_task_status(task).model_dump_json()
                    yield f"event: done\ndata: {payload}\n\n"
                    return
                time.sleep(0.25)
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
    return TaskArtifactsResponse.from_view(
        artifact_svc.get_task_result_view(task.task_id)
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
def get_task_result(
    task_id: str,
    task_svc: TaskService = Depends(task_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    task = task_svc.get_task(task_id)
    return TaskResultResponse.from_view(
        artifact_svc.get_task_result_view(task.task_id)
    )


@router.get("/{task_id}/preview", response_model=TaskPreviewResponse)
def get_task_preview(
    task_id: str,
    task_svc: TaskService = Depends(task_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    task = task_svc.get_task(task_id)
    return TaskPreviewResponse.from_view(
        artifact_svc.get_task_preview_view(task.task_id)
    )
