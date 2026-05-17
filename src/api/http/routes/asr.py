"""ASR routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import asr_service
from src.api.http.schemas.asr import (
    SubtitleSegmentResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from src.app.services import AsrService

router = APIRouter(prefix="/asr", tags=["asr"])


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
            SubtitleSegmentResponse(start=s.start, end=s.end, text=s.text)
            for s in result.segments
        ],
        output_path=result.output_path,
        text=result.text,
    )
