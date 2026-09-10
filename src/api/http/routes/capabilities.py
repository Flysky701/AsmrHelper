"""Capability descriptor routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import capability_descriptor_service
from src.api.http.schemas.capabilities import CapabilityDescriptorResponse
from src.app.services import CapabilityDescriptorService

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=list[CapabilityDescriptorResponse])
def list_capabilities(
    category: str | None = None,
    provider: str | None = None,
    svc: CapabilityDescriptorService = Depends(capability_descriptor_service),
):
    descriptors = svc.list_descriptors(category=category, provider=provider)
    return [CapabilityDescriptorResponse(**item) for item in descriptors]
