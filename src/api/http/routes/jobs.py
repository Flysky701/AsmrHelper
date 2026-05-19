"""HTTP routes for job management."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from src.api.http.dependencies import job_service, queue_runner
from src.api.http.schemas.jobs import (
    JobActionRequest,
    JobCreateRequest,
    JobDiscoverRequest,
    JobListResponse,
    JobResponse,
)
from src.app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_to_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        job_type=job.job_type,
        source_file=job.source_file,
        source_name=job.source_name,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        preset_id=job.preset_id,
        resolved_options=job.resolved_options,
        artifacts=job.artifacts,
        primary_output=job.primary_output,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        task_id=job.task_id,
    )


@router.post("", response_model=JobListResponse)
def create_jobs(req: JobCreateRequest, svc=Depends(job_service)):
    """Create one job per input file."""
    created = []
    for item in req.items:
        source_file = JobService.normalize_source_path(item.source_file)
        name = item.source_name or Path(source_file).name
        job = svc.create_job(
            source_file=source_file,
            source_name=name,
            preset_id=req.preset_id,
            resolved_options=req.resolved_options,
        )
        created.append(job)
    return JobListResponse(
        jobs=[_job_to_response(j) for j in created],
        total=len(created),
    )


@router.get("", response_model=JobListResponse)
def list_jobs(status: str | None = None, svc=Depends(job_service)):
    """List all jobs, optionally filtered by status."""
    jobs = svc.list_jobs(status=status)
    return JobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=len(jobs),
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, svc=Depends(job_service)):
    """Get a single job by ID."""
    job = svc.get_job(job_id)
    if not job:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    return _job_to_response(job)


@router.post("/start", response_model=JobListResponse)
def start_jobs(max_concurrent: int = 2, runner=Depends(queue_runner)):
    """Transition pending jobs to running and execute them."""
    started = runner.start_queue(max_concurrent=max_concurrent)
    return JobListResponse(
        jobs=[_job_to_response(j) for j in started],
        total=len(started),
    )


@router.post("/cancel", response_model=JobListResponse)
def cancel_jobs(req: JobActionRequest, runner=Depends(queue_runner)):
    """Cancel pending or running jobs."""
    cancelled = runner.cancel_jobs(req.job_ids)
    return JobListResponse(
        jobs=[_job_to_response(j) for j in cancelled],
        total=len(cancelled),
    )


@router.post("/discover")
def discover_files(req: JobDiscoverRequest):
    """Scan a directory for audio files."""
    directory = Path(req.directory)
    if not directory.is_dir():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"not a directory: {req.directory}")

    extensions = {e.lower() for e in req.extensions}
    files = sorted(
        str(p) for p in directory.rglob("*") if p.suffix.lower() in extensions and p.is_file()
    )
    return {"files": files, "count": len(files)}
