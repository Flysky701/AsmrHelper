"""Pipeline routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import batch_pipeline_service, pipeline_service
from src.api.http.schemas.pipeline import (
    BatchPipelineRequest,
    BatchPipelineResponse,
    BatchItemResultResponse,
    PipelinePresetsResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    ArtifactSetResponse,
    PresetItem,
    TaskStatusResponse,
)
from src.api.http.schemas.tasks import TaskCreateResponse, TaskSpecResponse
from src.app.dto import BatchPipelineRequest as BatchPipelineDTO, PipelineRequest
from src.app.services import BatchPipelineService, PipelineService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _build_task_response(result) -> TaskStatusResponse | None:
    if getattr(result, "task", None) is not None:
        return TaskStatusResponse.from_task_status(result.task)
    if result.task_id and result.task_state:
        return TaskStatusResponse(task_id=result.task_id, state=result.task_state)
    return None


def _to_pipeline_request(body: PipelineRunRequest) -> PipelineRequest:
    return PipelineRequest(
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
        translate_model=body.translate_model,
        tts_speed=body.tts_speed,
        original_volume=body.original_volume,
        tts_volume_ratio=body.tts_volume_ratio,
        tts_delay=body.tts_delay,
        skip_existing=body.skip_existing,
        voice_profile_id=body.voice_profile_id,
        engine_params=body.engine_params,
    )


@router.post("/tasks", response_model=TaskCreateResponse)
def create_pipeline_task(
    body: PipelineRunRequest,
    svc: PipelineService = Depends(pipeline_service),
):
    task, spec = svc.create_pipeline_task(
        _to_pipeline_request(body),
        task_source="desktop-workbench",
    )
    return TaskCreateResponse(
        task=TaskStatusResponse.from_task_status(task),
        spec=TaskSpecResponse.from_task_spec(spec),
    )


@router.post("/run", response_model=PipelineRunResponse)
def run_pipeline(
    body: PipelineRunRequest,
    svc: PipelineService = Depends(pipeline_service),
):
    result = svc.run_audio_pipeline(_to_pipeline_request(body))
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
def list_presets(
    svc: PipelineService = Depends(pipeline_service),
):
    raw = svc.list_presets()
    return PipelinePresetsResponse(
        presets=[
            PresetItem(
                id=p["id"],
                label=p["label"],
                description=p.get("description", ""),
                stages=p.get("stages", []),
            )
            for p in raw
        ]
    )


@router.post("/batch", response_model=BatchPipelineResponse)
def run_batch(
    body: BatchPipelineRequest,
    svc: BatchPipelineService = Depends(batch_pipeline_service),
):
    request = BatchPipelineDTO(
        input_files=body.input_files,
        input_dir=body.input_dir,
        output_base_dir=body.output_base_dir,
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
        max_workers=body.max_workers,
        use_batch_output_structure=body.use_batch_output_structure,
        voice_profile_id=body.voice_profile_id,
    )
    result = svc.run_batch(request)
    return BatchPipelineResponse(
        items=[
            BatchItemResultResponse(
                file=item.file,
                status=item.status,
                task_id=item.task_id,
                output=item.output,
                error=item.error,
                duration=item.duration,
            )
            for item in result.items
        ],
        total_count=result.total_count,
        success_count=result.success_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        total_duration=result.total_duration,
    )
