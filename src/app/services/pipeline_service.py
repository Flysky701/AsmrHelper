"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading

from src.core import Pipeline, PipelineConfig

from ..dto import ArtifactSet, PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError
from .resource_service import ResourceService, get_resource_service
from .task_service import TaskService, get_task_service


LANG_MAP = {
    "ja": ("鏃ユ枃", "涓枃"),
    "zh": ("涓枃", "鑻辨枃"),
    "en": ("鑻辨枃", "涓枃"),
}


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

        task = self._task_service.create_task("pipeline")
        current_task = self._task_service.start_task(task.task_id, message="running pipeline")

        try:
            workspace = self._resource_service.ensure_workspace()
            output_dir = request.output_dir or str(workspace["output_dir"])
            current_task = self._task_service.update_progress(
                task.task_id,
                progress=0.1,
                message="preparing workspace",
            )

            source_label, target_label = LANG_MAP.get(request.source_lang, ("鏃ユ枃", "涓枃"))
            if request.target_lang == "zh":
                target_label = "涓枃"
            elif request.target_lang == "en":
                target_label = "鑻辨枃"
            elif request.target_lang == "ja":
                target_label = "鏃ユ枃"

            config = PipelineConfig(
                input_path=request.input_path,
                output_dir=output_dir,
                use_vocal_separator=True,
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
                use_mixer=True,
                tts_delay_ms=request.tts_delay,
                skip_existing=request.skip_existing,
            )

            def on_progress(progress: float, message: str = "") -> None:
                nonlocal current_task
                current_task = self._task_service.update_progress(
                    task.task_id,
                    progress=progress,
                    message=message,
                )

            results = Pipeline(config).run(
                preset="asmr_bilingual",
                progress_callback=on_progress,
            )
        except Exception as exc:
            current_task = self._task_service.fail_task(
                task.task_id,
                message="pipeline failed",
                detail=str(exc),
            )
            if isinstance(exc, AppValidationError):
                raise
            raise AppExecutionError(str(exc)) from exc

        current_task = self._task_service.update_progress(
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
            artifacts=ArtifactSet(
                files={
                    name: path
                    for name, path in {
                        "mix": mix_path,
                        "subtitle": exported_subtitle,
                    }.items()
                    if path
                },
                primary_output=mix_path or exported_subtitle,
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
