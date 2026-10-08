"""Persistent batch-run routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import batch_run_service
from src.api.http.schemas.batch_runs import (
    BatchDiscoverRequest,
    BatchDiscoverResponse,
    BatchRunCreateRequest,
    BatchRunListResponse,
    BatchRunResponse,
    BatchItemRemovalRequest,
)
from src.app.services import BatchRunService


router = APIRouter(prefix="/batch-runs", tags=["batch-runs"])


@router.post("/{batch_id}/items/{item_id}/removal", response_model=BatchRunResponse)
def set_unsubmitted_item_removed(batch_id: str, item_id: str, body: BatchItemRemovalRequest,
                                svc: BatchRunService = Depends(batch_run_service)):
    return BatchRunResponse.from_record(svc.set_unsubmitted_item_removed(batch_id, item_id, **body.model_dump()))


@router.post("/discover", response_model=BatchDiscoverResponse)
def discover_batch_inputs(
    body: BatchDiscoverRequest,
    svc: BatchRunService = Depends(batch_run_service),
):
    options = {"recursive": body.recursive}
    if body.limit is not None:
        options["limit"] = body.limit
    if body.media_kind != "audio":
        options["media_kind"] = body.media_kind
    files = svc.discover_audio_files(body.directory, **options)
    return BatchDiscoverResponse(directory=body.directory, files=files)


@router.post("", response_model=BatchRunResponse, status_code=202)
def create_batch_run(
    body: BatchRunCreateRequest,
    svc: BatchRunService = Depends(batch_run_service),
):
    record = svc.create_batch(
        name=body.name,
        inputs=[item.model_dump() for item in body.inputs],
        output_dir=body.output.directory,
        execution_profile=body.execution_profile.model_dump(),
        max_parallel=body.max_parallel,
        groups=[group.model_dump(exclude_none=True) for group in body.groups],
        client_request_id=body.client_request_id,
    )
    return BatchRunResponse.from_record(record)


@router.get("", response_model=BatchRunListResponse)
def list_batch_runs(svc: BatchRunService = Depends(batch_run_service)):
    return BatchRunListResponse(
        batches=[BatchRunResponse.from_record(record) for record in svc.list_batches()]
    )


@router.get("/{batch_id}", response_model=BatchRunResponse)
def get_batch_run(
    batch_id: str,
    svc: BatchRunService = Depends(batch_run_service),
):
    return BatchRunResponse.from_record(svc.get_batch(batch_id))


@router.post("/{batch_id}/cancel", response_model=BatchRunResponse)
def cancel_batch_run(
    batch_id: str,
    svc: BatchRunService = Depends(batch_run_service),
):
    return BatchRunResponse.from_record(svc.request_cancel(batch_id))


@router.post("/{batch_id}/retry-failed", response_model=BatchRunResponse)
def retry_failed_batch_items(
    batch_id: str,
    svc: BatchRunService = Depends(batch_run_service),
):
    return BatchRunResponse.from_record(svc.retry_failed(batch_id))
