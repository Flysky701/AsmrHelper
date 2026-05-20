"""TTS routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tts_engine_service, tts_service
from src.api.http.schemas.tts import (
    SynthesizeRequest,
    SynthesizeResponse,
    TtsEngineDescriptorResponse,
    TtsEngineListResponse,
)
from src.app.services import TtsEngineService, TtsService

router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("/engines", response_model=TtsEngineListResponse)
def list_tts_engines(
    svc: TtsEngineService = Depends(tts_engine_service),
):
    engines = [TtsEngineDescriptorResponse(**descriptor) for descriptor in svc.list_engines()]
    return TtsEngineListResponse(engines=engines)


@router.get("/engines/{engine_id}", response_model=TtsEngineDescriptorResponse)
def get_tts_engine(
    engine_id: str,
    svc: TtsEngineService = Depends(tts_engine_service),
):
    return TtsEngineDescriptorResponse(**svc.get_engine(engine_id))


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
