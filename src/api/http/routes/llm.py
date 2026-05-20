"""LLM provider routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import llm_capability_service
from src.api.http.schemas.translation import (
    LlmProviderDescriptorResponse,
    LlmProviderListResponse,
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
