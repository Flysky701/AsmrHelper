"""Application-layer wrapper for batch audio pipeline workflows."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from src.utils.constants import AUDIO_EXTENSIONS

from ..dto import BatchItemResult, BatchPipelineRequest, BatchPipelineResult, PipelineRequest
from ..errors import AppExecutionError, AppValidationError
from .input_catalog_service import InputCatalogService, get_input_catalog_service
from .pipeline_service import PipelineService, get_pipeline_service
from .session_service import SessionService, get_session_service
from .task_service import TaskService, get_task_service


ProgressCallback = Callable[[int, int, BatchItemResult], None]


class BatchPipelineService:
    """Normalize batch orchestration behind the app layer."""

    def __init__(
        self,
        pipeline_service: PipelineService | None = None,
        task_service: TaskService | None = None,
        session_service: SessionService | None = None,
        input_catalog_service: InputCatalogService | None = None,
    ) -> None:
        self._pipeline_service = pipeline_service or get_pipeline_service()
        self._task_service = task_service or get_task_service()
        self._session_service = session_service or get_session_service()
        self._input_catalog_service = input_catalog_service or get_input_catalog_service()

    def discover_audio_files(self, directory: str) -> list[Path]:
        if not directory:
            raise AppValidationError("input_dir is required")

        root = Path(directory)
        if not root.exists():
            raise AppValidationError(f"input directory does not exist: {directory}")
        if not root.is_dir():
            raise AppValidationError(f"input_dir is not a directory: {directory}")

        audio_files: list[Path] = []
        for extension in AUDIO_EXTENSIONS:
            audio_files.extend(root.rglob(f"*{extension}"))
        return sorted(audio_files)

    def run_batch(
        self,
        request: BatchPipelineRequest,
        progress_callback: ProgressCallback | None = None,
        cancel_event=None,
    ) -> BatchPipelineResult:
        input_files = self._resolve_input_files(request)
        total = len(input_files)
        if total == 0:
            raise AppValidationError("no input files provided")
        if request.max_workers < 1:
            raise AppValidationError("max_workers must be at least 1")

        started_at = time.time()
        items: list[BatchItemResult] = []
        task_specs = self.create_batch_task_specs(request, input_files=input_files)

        if request.max_workers == 1:
            for index, task_spec in enumerate(task_specs, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    break
                item = self._process_one(task_spec.task_id, request)
                items.append(item)
                if progress_callback is not None:
                    progress_callback(index, total, item)
        else:
            with ThreadPoolExecutor(max_workers=request.max_workers) as executor:
                futures = {
                    executor.submit(self._process_one, task_spec.task_id, request): task_spec.task_id
                    for task_spec in task_specs
                }
                completed = 0
                for future in as_completed(futures):
                    if cancel_event is not None and cancel_event.is_set():
                        for pending in futures:
                            pending.cancel()
                        break

                    completed += 1
                    task_id = futures[future]
                    try:
                        item = future.result()
                    except Exception as exc:
                        item = BatchItemResult(
                            file=task_id,
                            status="failed",
                            task_id=task_id,
                            error=str(exc),
                        )
                    items.append(item)
                    if progress_callback is not None:
                        progress_callback(completed, total, item)

            items.sort(key=lambda item: item.file)

        success_count = sum(1 for item in items if item.status == "success")
        skipped_count = sum(1 for item in items if item.status == "skipped")
        failed_count = sum(1 for item in items if item.status == "failed")
        return BatchPipelineResult(
            items=items,
            total_count=total,
            success_count=success_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            total_duration=time.time() - started_at,
        )

    def create_batch_task_specs(
        self,
        request: BatchPipelineRequest,
        *,
        input_files: list[Path] | None = None,
    ):
        resolved_input_files = input_files or self._resolve_input_files(request)
        task_specs = []
        for input_path in resolved_input_files:
            output_dir, batch_root_dir = self._resolve_task_output(request, input_path)
            pipeline_request = PipelineRequest(
                input_path=str(input_path),
                output_dir=output_dir,
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                use_vocal_separator=request.use_vocal_separator,
                tts_engine=request.tts_engine,
                tts_voice=request.tts_voice,
                vocal_model=request.vocal_model,
                asr_model=request.asr_model,
                translate_provider=request.translate_provider,
                tts_speed=request.tts_speed,
                original_volume=request.original_volume,
                tts_volume_ratio=request.tts_volume_ratio,
                tts_delay=request.tts_delay,
                skip_existing=request.skip_existing,
                voice_profile_id=request.voice_profile_id,
                output_mode="batch" if request.use_batch_output_structure else "single",
                batch_root_dir=batch_root_dir,
            )
            task_specs.append(
                self._pipeline_service.create_pipeline_task_spec(
                    pipeline_request,
                    task_source="batch-pipeline",
                )
            )
        return task_specs

    def _resolve_input_files(self, request: BatchPipelineRequest) -> list[Path]:
        if request.input_files and request.input_dir:
            raise AppValidationError("input_files and input_dir are mutually exclusive")
        if request.input_files:
            input_files = [Path(path) for path in request.input_files]
        elif request.input_dir:
            input_files = self.discover_audio_files(request.input_dir)
        else:
            raise AppValidationError("either input_files or input_dir is required")

        missing = [path for path in input_files if not path.exists()]
        if missing:
            raise AppValidationError(
                "input files do not exist: " + ", ".join(str(path) for path in missing)
            )
        return input_files

    def _process_one(self, task_id: str, request: BatchPipelineRequest) -> BatchItemResult:
        started_at = time.time()
        try:
            task_spec = self._task_service.get_task_spec(task_id)
            session = self._session_service.get_session(task_spec.session_id)
            input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
            input_path = Path(input_asset.absolute_path)
            _, batch_root_dir = self._resolve_task_output(request, input_path)
            if request.use_batch_output_structure:
                expected_output = str(
                    Path(batch_root_dir) / "Main_Product" / f"{input_path.stem}_mix{input_path.suffix}"
                )
            else:
                expected_output = self._resolve_existing_single_output(input_path, Path(session.resolved_output_dir))

            if request.skip_existing and Path(expected_output).exists():
                self._task_service.skip_task(
                    task_id,
                    message="pipeline skipped",
                    detail=expected_output,
                )
                return BatchItemResult(
                    file=str(input_path),
                    status="skipped",
                    task_id=task_id,
                    output=expected_output,
                    duration=time.time() - started_at,
                )

            pipeline_result = self._pipeline_service.run_pipeline_task(task_id)
            output = pipeline_result.mix_path or pipeline_result.artifacts.primary_output
            if not output:
                raise AppExecutionError("pipeline did not return a primary output")

            return BatchItemResult(
                file=str(input_path),
                status="success",
                task_id=task_id,
                output=output,
                duration=time.time() - started_at,
            )
        except Exception as exc:
            return BatchItemResult(
                file=str(task_id),
                status="failed",
                task_id=task_id,
                error=str(exc),
                duration=time.time() - started_at,
            )

    def _sanitize_output_name(self, input_path: Path) -> str:
        return "".join(
            char if char.isalnum() or char in " _-()" else "_"
            for char in input_path.stem
        )

    def _resolve_output_dir(self, input_path: Path, output_base_dir: str) -> Path:
        safe_name = self._sanitize_output_name(input_path)
        if output_base_dir:
            return Path(output_base_dir) / safe_name
        return input_path.parent / f"{safe_name}_output"

    def _resolve_task_output(self, request: BatchPipelineRequest, input_path: Path) -> tuple[str, str]:
        if request.use_batch_output_structure:
            return "", request.output_base_dir or str(input_path.parent / "output")
        return str(self._resolve_output_dir(input_path, request.output_base_dir)), ""

    def _resolve_existing_single_output(self, input_path: Path, output_dir: Path) -> str:
        task_output = output_dir / f"{input_path.stem}_mix{input_path.suffix}"
        legacy_output = output_dir / "final_mix.wav"
        if task_output.exists():
            return str(task_output)
        return str(legacy_output)


_service: BatchPipelineService | None = None
_lock = threading.Lock()


def get_batch_pipeline_service() -> BatchPipelineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = BatchPipelineService()
    return _service
