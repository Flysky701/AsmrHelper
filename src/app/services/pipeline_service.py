"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading

from ..dto import ArtifactSet, PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError
from .resource_service import ResourceService, get_resource_service
from .task_service import TaskService, get_task_service


LANG_MAP = {
    "ja": ("日文", "中文"),
    "zh": ("中文", "英文"),
    "en": ("英文", "中文"),
}

SUPPORTED_LANGUAGE_CODES = frozenset(LANG_MAP)
PROGRESS_MESSAGE_DEFAULT = 0.1
Pipeline = None
PipelineConfig = None


def _load_pipeline_runtime():
    global Pipeline
    global PipelineConfig
    if Pipeline is None or PipelineConfig is None:
        from src.core import Pipeline as core_pipeline
        from src.core import PipelineConfig as core_pipeline_config

        if Pipeline is None:
            Pipeline = core_pipeline
        if PipelineConfig is None:
            PipelineConfig = core_pipeline_config
    return Pipeline, PipelineConfig


def _get_step_errors(results: dict) -> dict[str, str]:
    step_errors: dict[str, str] = {}
    for step_name, step_result in results.get("steps", {}).items():
        if isinstance(step_result, dict) and step_result.get("error"):
            step_errors[step_name] = str(step_result["error"])
    return step_errors


class PipelineService:
    """Wrap core pipeline invocation behind stable request/result DTOs."""

    def __init__(
        self,
        task_service: TaskService | None = None,
        resource_service: ResourceService | None = None,
    ) -> None:
        self._task_service = task_service or get_task_service()
        self._resource_service = resource_service or get_resource_service()

    def run_audio_pipeline(self, request: PipelineRequest) -> PipelineResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        if request.source_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported source_lang: {request.source_lang}")
        if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported target_lang: {request.target_lang}")

        task = self._task_service.create_task("pipeline")
        self._task_service.start_task(task.task_id, message="running pipeline")

        try:
            workspace = self._resource_service.ensure_workspace()
            output_dir = request.output_dir or str(workspace["output_dir"])
            self._task_service.update_progress(
                task.task_id,
                progress=0.1,
                message="preparing workspace",
            )

            source_label, _ = LANG_MAP[request.source_lang]
            target_label = LANG_MAP[request.target_lang][0]
            pipeline_class, pipeline_config_class = _load_pipeline_runtime()

            config = pipeline_config_class(
                input_path=request.input_path,
                output_dir=output_dir,
                vtt_path=request.vtt_path,
                use_vocal_separator=request.use_vocal_separator,
                vocal_model=request.vocal_model,
                asr_model=request.asr_model,
                asr_language=request.source_lang,
                use_translate=True,
                translate_provider=request.translate_provider,
                source_lang=source_label,
                target_lang=target_label,
                use_tts=True,
                tts_engine=request.tts_engine,
                tts_voice=request.tts_voice,
                tts_speed=request.tts_speed,
                use_mixer=True,
                original_volume=request.original_volume,
                tts_volume_ratio=request.tts_volume_ratio,
                tts_delay_ms=request.tts_delay,
                skip_existing=request.skip_existing,
            )

            def on_progress(message: str) -> None:
                self._task_service.update_progress(
                    task.task_id,
                    progress=PROGRESS_MESSAGE_DEFAULT,
                    message=message,
                )

            results = pipeline_class(config).run(
                preset="asmr_bilingual",
                progress_callback=on_progress,
            )
            step_errors = _get_step_errors(results)
            if step_errors:
                detail = "; ".join(
                    f"{step_name}: {error_message}"
                    for step_name, error_message in step_errors.items()
                )
                raise AppExecutionError(f"pipeline reported step errors: {detail}")
        except Exception as exc:
            self._task_service.fail_task(
                task.task_id,
                message="pipeline failed",
                detail=str(exc),
            )
            if isinstance(exc, (AppValidationError, AppExecutionError)):
                raise
            raise AppExecutionError(str(exc)) from exc

        self._task_service.update_progress(
            task.task_id,
            progress=0.9,
            message="pipeline finished",
        )
        mix_path = results.get("mix_path")
        exported_subtitle = results.get("exported_subtitle")
        completed_task = self._task_service.complete_task(
            task.task_id,
            message="pipeline completed",
            detail=mix_path or exported_subtitle or "",
        )

        return PipelineResult(
            success=True,
            input_path=results.get("input", request.input_path),
            task=completed_task,
            task_id=completed_task.task_id,
            task_state=completed_task.state,
            artifacts=ArtifactSet.from_optional_paths(
                primary_output=mix_path or exported_subtitle,
                mix=mix_path,
                subtitle=exported_subtitle,
            ),
            mix_path=mix_path,
            exported_subtitle=exported_subtitle,
            steps=results.get("steps", {}),
            total_duration=float(results.get("total_duration", 0.0)),
            error_message=results.get("error"),
        )


_service: PipelineService | None = None
_lock = threading.Lock()


def get_pipeline_service() -> PipelineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PipelineService()
    return _service
