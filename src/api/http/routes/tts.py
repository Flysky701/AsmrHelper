"""TTS routes — engine-driven entry point."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from src.api.http.dependencies import tts_engine_service
from src.api.http.schemas.tts import (
    SynthesizeRequest,
    SynthesizeResponse,
    TtsEngineDescriptorResponse,
    TtsEngineListResponse,
)
from src.app.services import TtsEngineService

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
    svc: TtsEngineService = Depends(tts_engine_service),
):
    source = Path(body.input_path)
    if not source.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"input file does not exist: {body.input_path}")
    text = source.read_text(encoding="utf-8")
    result = svc.synthesize_text(
        text=text,
        output_path=body.output_path,
        provider=body.engine,
        common_options={"voice": body.voice},
    )
    return SynthesizeResponse(
        engine=result.engine,
        voice=result.voice,
        output_path=result.output_path,
    )
