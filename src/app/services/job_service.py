"""In-memory job store for the task queue workbench."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from ..dto.job import Job
from ..errors import AppValidationError


class JobService:
    """CRUD operations for Job objects. Thread-safe in-memory store."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        source_file: str,
        source_name: str,
        job_type: str = "pipeline",
        preset_id: str = "",
        resolved_options: dict | None = None,
    ) -> Job:
        """Create a new job in pending status."""
        source_file = self.normalize_source_path(source_file)
        source_name = source_name.strip().strip('"').strip("'")
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        job = Job(
            job_id=job_id,
            job_type=job_type,
            source_file=source_file,
            source_name=source_name,
            status="pending",
            preset_id=preset_id,
            resolved_options=resolved_options or {},
            created_at=now,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    @staticmethod
    def normalize_source_path(source_file: str) -> str:
        """Normalize user-entered path text before it reaches the pipeline."""
        source_file = source_file.strip()
        if len(source_file) >= 2 and source_file[0] == source_file[-1] and source_file[0] in {'"', "'"}:
            source_file = source_file[1:-1].strip()
        return source_file

    def get_job(self, job_id: str) -> Optional[Job]:
        """Return a job by ID, or None."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[Job]:
        """List all jobs, optionally filtered by status."""
        with self._lock:
            jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.created_at)

    def update_status(
        self,
        job_id: str,
        status: str,
        stage: str = "",
        progress: float = 0.0,
        error: str | None = None,
        task_id: str | None = None,
    ) -> Job:
        """Update job status fields."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise AppValidationError(f"job not found: {job_id}")
            job.status = status
            if stage:
                job.stage = stage
            if progress:
                job.progress = progress
            if error is not None:
                job.error = error
            if task_id is not None:
                job.task_id = task_id
            if status == "running" and job.started_at is None:
                job.started_at = time.time()
            if status in ("completed", "failed", "cancelled"):
                job.finished_at = time.time()
            return job

    def set_artifacts(
        self,
        job_id: str,
        artifacts: dict[str, str],
        primary_output: str | None = None,
    ) -> Job:
        """Attach output artifacts to a job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise AppValidationError(f"job not found: {job_id}")
            job.artifacts = artifacts
            if primary_output is not None:
                job.primary_output = primary_output
            return job

    def cancel_jobs(self, job_ids: list[str]) -> list[Job]:
        """Cancel pending jobs.

        Running jobs are not marked as cancelled because the current
        pipeline execution path is not cooperatively interruptible.
        """
        cancelled = []
        with self._lock:
            for jid in job_ids:
                job = self._jobs.get(jid)
                if job and job.status == "pending":
                    job.status = "cancelled"
                    job.stage = "cancelled"
                    job.finished_at = time.time()
                    cancelled.append(job)
        return cancelled

    def start_pending(self, max_concurrent: int = 2) -> list[Job]:
        """Transition up to max_concurrent pending jobs to running.
        Returns the list of jobs that were started."""
        started = []
        with self._lock:
            running_count = sum(1 for j in self._jobs.values() if j.status == "running")
            available = max_concurrent - running_count
            if available <= 0:
                return []
            for job in sorted(self._jobs.values(), key=lambda j: j.created_at):
                if len(started) >= available:
                    break
                if job.status == "pending":
                    job.status = "running"
                    job.started_at = time.time()
                    started.append(job)
        return started


_service: JobService | None = None
_lock = threading.Lock()


def get_job_service() -> JobService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = JobService()
    return _service
