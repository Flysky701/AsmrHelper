"""Concurrent queue executor for the workbench job system.

Orchestrates JobService + PipelineService + TaskService.
Transitions pending jobs to running, executes them via PipelineService,
and auto-starts the next pending job on completion.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ..dto import PipelineRequest
from ..dto.job import Job
from ..errors import AppExecutionError, AppValidationError
from .job_service import JobService, get_job_service
from .pipeline_service import PipelineService, get_pipeline_service

log = logging.getLogger(__name__)


class QueueRunner:
    """Execute jobs from the queue with bounded concurrency."""

    def __init__(
        self,
        job_service: JobService | None = None,
        pipeline_service: PipelineService | None = None,
        max_concurrent: int = 2,
    ) -> None:
        self._jobs = job_service or get_job_service()
        self._pipeline = pipeline_service or get_pipeline_service()
        self._max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()

    def start_queue(self, max_concurrent: int | None = None) -> list[Job]:
        """Transition pending jobs to running and submit them for execution."""
        concurrent = max_concurrent or self._max_concurrent
        started = self._jobs.start_pending(max_concurrent=concurrent)
        for job in started:
            self._submit(job)
        return started

    def _submit(self, job: Job) -> None:
        """Submit a job to the thread pool."""
        self._executor.submit(self._run_job, job.job_id)

    def _run_job(self, job_id: str) -> None:
        """Execute a single job. Called from the thread pool."""
        job = self._jobs.get_job(job_id)
        if not job or job.status != "running":
            return

        try:
            self._jobs.update_status(job_id, status="running", stage="preparing")

            request = self._build_request(job)
            self._jobs.update_status(
                job_id,
                status="running",
                stage="processing",
                progress=0.1,
            )

            result = self._pipeline.run_audio_pipeline(request)

            artifacts = {}
            if result.artifacts:
                artifacts = dict(result.artifacts.files)
            self._jobs.set_artifacts(
                job_id,
                artifacts=artifacts,
                primary_output=result.artifacts.primary_output if result.artifacts else None,
            )
            if result.task_id:
                self._jobs.update_status(
                    job_id,
                    status="running",
                    task_id=result.task_id,
                )

            self._jobs.update_status(
                job_id,
                status="completed",
                stage="done",
                progress=1.0,
            )
            log.info("job %s completed", job_id)

        except (AppValidationError, AppExecutionError) as exc:
            self._jobs.update_status(
                job_id,
                status="failed",
                stage="error",
                error=str(exc),
            )
            log.warning("job %s failed: %s", job_id, exc)

        except Exception as exc:
            self._jobs.update_status(
                job_id,
                status="failed",
                stage="error",
                error=str(exc),
            )
            log.exception("job %s failed with unexpected error", job_id)

        # Auto-start next pending jobs
        self._auto_start()

    def _build_request(self, job: Job) -> PipelineRequest:
        """Convert a Job into a PipelineRequest."""
        opts = dict(job.resolved_options)
        return PipelineRequest(
            input_path=job.source_file,
            output_dir=opts.pop("output_dir", ""),
            vtt_path=opts.pop("vtt_path", None),
            source_lang=opts.pop("source_lang", "ja"),
            target_lang=opts.pop("target_lang", "zh"),
            use_vocal_separator=opts.pop("use_vocal_separator", True),
            tts_engine=opts.pop("tts_engine", "edge"),
            tts_voice=opts.pop("tts_voice", "zh-CN-XiaoxiaoNeural"),
            vocal_model=opts.pop("vocal_model", "htdemucs"),
            asr_model=opts.pop("asr_model", "base"),
            translate_provider=opts.pop("translate_provider", "deepseek"),
            tts_speed=opts.pop("tts_speed", 1.0),
            original_volume=opts.pop("original_volume", 0.85),
            tts_volume_ratio=opts.pop("tts_volume_ratio", 0.5),
            tts_delay=opts.pop("tts_delay", 0.0),
            skip_existing=opts.pop("skip_existing", False),
            voice_profile_id=opts.pop("voice_profile_id", None),
        )

    def _auto_start(self) -> None:
        """Start next pending jobs if concurrency allows."""
        with self._lock:
            started = self._jobs.start_pending(max_concurrent=self._max_concurrent)
            for job in started:
                self._submit(job)

    def cancel_jobs(self, job_ids: list[str]) -> list[Job]:
        """Cancel specified jobs."""
        return self._jobs.cancel_jobs(job_ids)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool."""
        self._executor.shutdown(wait=wait)


_runner: QueueRunner | None = None
_lock = threading.Lock()


def get_queue_runner() -> QueueRunner:
    global _runner
    if _runner is None:
        with _lock:
            if _runner is None:
                _runner = QueueRunner()
    return _runner
