"""Task routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import artifact_service, task_service
from src.api.http.schemas.tasks import (
    ArtifactRecordResponse,
    TaskBatchCreateRequest,
    TaskBatchCreateResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskArtifactsResponse,
    TaskListResponse,
    TaskResultResponse,
    TaskSpecResponse,
    TaskStatusResponse,
)
from src.app.services import ArtifactService, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


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


@router.get("", response_model=TaskListResponse)
def list_tasks(
    svc: TaskService = Depends(task_service),
):
    tasks = svc.list_tasks()
    return TaskListResponse.from_tasks(tasks)


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(
    task_id: str,
    svc: TaskService = Depends(task_service),
):
    task = svc.get_task(task_id)
    return TaskStatusResponse.from_task_status(task)


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
