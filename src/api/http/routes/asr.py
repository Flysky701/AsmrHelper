"""ASR routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import asr_engine_service, asr_service
from src.api.http.schemas.asr import (
    AsrEngineDescriptorResponse,
    AsrEngineListResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from src.api.http.schemas.subtitles import SubtitleSegmentModel
from src.app.services import AsrEngineService, AsrService

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
    svc: AsrService = Depends(asr_service),
):
    result = svc.transcribe_file(
        input_path=body.input_path,
        output_path=body.output_path,
        model=body.model,
        language=body.language,
    )
    return TranscribeResponse(
        segments=[
            SubtitleSegmentModel(start=s.start, end=s.end, text=s.text)
            for s in result.segments
        ],
        output_path=result.output_path,
        text=result.text,
    )
