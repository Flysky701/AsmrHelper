"""TTS routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tts_service
from src.api.http.schemas.tts import SynthesizeRequest, SynthesizeResponse
from src.app.services import TtsService

router = APIRouter(prefix="/tts", tags=["tts"])


@router.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(
    body: SynthesizeRequest,
    svc: TtsService = Depends(tts_service),
):
    result = svc.synthesize_file(
        input_path=body.input_path,
        output_path=body.output_path,
        engine=body.engine,
        voice=body.voice,
    )
    return SynthesizeResponse(
        engine=result.engine,
        voice=result.voice,
        output_path=result.output_path,
    )
