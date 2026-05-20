"""LLM provider routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from src.api.http.dependencies import llm_capability_service
from src.api.http.schemas.translation import (
    LlmProviderDescriptorResponse,
    LlmProviderListResponse,
    TranslateRequest,
    TranslateResponse,
)
from src.app.services import LlmCapabilityService

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers", response_model=LlmProviderListResponse)
def list_llm_providers(
    svc: LlmCapabilityService = Depends(llm_capability_service),
):
    providers = [LlmProviderDescriptorResponse(**descriptor) for descriptor in svc.list_providers()]
    return LlmProviderListResponse(providers=providers)


@router.get("/providers/{provider_id}", response_model=LlmProviderDescriptorResponse)
def get_llm_provider(
    provider_id: str,
    svc: LlmCapabilityService = Depends(llm_capability_service),
):
    return LlmProviderDescriptorResponse(**svc.get_provider(provider_id))


@router.post("/translate", response_model=TranslateResponse)
def translate(
    body: TranslateRequest,
    svc: LlmCapabilityService = Depends(llm_capability_service),
):
    source = Path(body.input_path)
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"input file does not exist: {body.input_path}")

    texts = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = svc.translate_texts(
        texts=texts,
        provider=body.provider,
        output_path=body.output_path,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
    )
    return TranslateResponse(
        items=result.items,
        provider=result.provider,
        source_lang=result.source_lang,
        target_lang=result.target_lang,
    )
