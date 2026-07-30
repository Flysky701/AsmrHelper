"""ASR routes — engine-driven entry point."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import asr_engine_service
from src.api.http.schemas.asr import (
    AsrEngineDescriptorResponse,
    AsrEngineListResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from src.api.http.schemas.subtitles import SubtitleSegmentModel
from src.app.services import AsrEngineService

router = APIRouter(prefix="/asr", tags=["asr"])


@router.get("/engines", response_model=AsrEngineListResponse)
def list_asr_engines(
    svc: AsrEngineService = Depends(asr_engine_service),
):
    engines = [AsrEngineDescriptorResponse(**descriptor) for descriptor in svc.list_engines()]
    return AsrEngineListResponse(engines=engines)


@router.get("/engines/{engine_id}", response_model=AsrEngineDescriptorResponse)
def get_asr_engine(
    engine_id: str,
    svc: AsrEngineService = Depends(asr_engine_service),
):
    return AsrEngineDescriptorResponse(**svc.get_engine(engine_id))


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe(
    body: TranscribeRequest,
    svc: AsrEngineService = Depends(asr_engine_service),
):
    common_options = dict(body.common_options)
    common_options.setdefault("language", body.language)
    provider_options = dict(body.provider_options)
    if body.provider == "faster_whisper":
        provider_options.setdefault("vad_filter", False)

    result = svc.transcribe_file(
        input_path=body.input_path,
        output_path=body.output_path,
        provider=body.provider,
        model=body.model,
        language=body.language,
        common_options=common_options,
        provider_options=provider_options,
    )
    return TranscribeResponse(
        segments=[
            SubtitleSegmentModel(start=s.start, end=s.end, text=s.text)
            for s in result.segments
        ],
        output_path=result.output_path,
        text=result.text,
    )
