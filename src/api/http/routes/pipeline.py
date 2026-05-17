"""Pipeline routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import pipeline_service
from src.api.http.schemas.pipeline import (
    PipelinePresetsResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    ArtifactSetResponse,
    TaskStatusResponse,
)
from src.app.dto import PipelineRequest
from src.app.services import PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _build_task_response(result) -> TaskStatusResponse | None:
    if getattr(result, "task", None) is not None:
        task = result.task
        return TaskStatusResponse(
            task_id=task.task_id,
            state=task.state,
            progress=task.progress,
            message=task.message,
            detail=task.detail,
        )
    if result.task_id and result.task_state:
        return TaskStatusResponse(task_id=result.task_id, state=result.task_state)
    return None


@router.post("/run", response_model=PipelineRunResponse)
def run_pipeline(
    body: PipelineRunRequest,
    svc: PipelineService = Depends(pipeline_service),
):
    request = PipelineRequest(
        input_path=body.input_path,
        output_dir=body.output_dir,
        vtt_path=body.vtt_path,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        use_vocal_separator=body.use_vocal_separator,
        tts_engine=body.tts_engine,
        tts_voice=body.tts_voice,
        vocal_model=body.vocal_model,
        asr_model=body.asr_model,
        translate_provider=body.translate_provider,
        tts_speed=body.tts_speed,
        original_volume=body.original_volume,
        tts_volume_ratio=body.tts_volume_ratio,
        tts_delay=body.tts_delay,
        skip_existing=body.skip_existing,
    )
    result = svc.run_audio_pipeline(request)
    task = _build_task_response(result)
    return PipelineRunResponse(
        success=result.success,
        input_path=result.input_path,
        task=task,
        task_id=result.task_id,
        task_state=result.task_state,
        artifacts=ArtifactSetResponse(
            files=result.artifacts.files,
            primary_output=result.artifacts.primary_output,
        ),
        mix_path=result.mix_path,
        exported_subtitle=result.exported_subtitle,
        total_duration=result.total_duration,
        error_message=result.error_message,
    )


@router.get("/presets", response_model=PipelinePresetsResponse)
def list_presets():
    return PipelinePresetsResponse(
        presets=["asmr_bilingual", "asr_only", "tts_only", "auto_subtitle"]
    )
