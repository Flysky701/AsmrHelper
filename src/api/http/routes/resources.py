"""Resource routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import resource_service
from src.api.http.schemas.resources import ResourceStatusListResponse, ResourceStatusResponse
from src.app.services import ResourceService

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("/status", response_model=ResourceStatusListResponse)
def get_resource_status(
    svc: ResourceService = Depends(resource_service),
):
    statuses = svc.check_required_resources()
    return ResourceStatusListResponse(
        resources=[
            ResourceStatusResponse(
                name=s.name,
                available=s.available,
                detail=s.detail,
                metadata=s.metadata,
            )
            for s in statuses
        ]
    )
