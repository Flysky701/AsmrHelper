"""Resource routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import resource_service
from src.api.http.schemas.resources import (
    ResourceStatusListResponse,
    ResourceStatusResponse,
    RuntimeCapabilitiesResponse,
    RuntimeResourcesResponse,
    TaskReadinessRequest,
    TaskReadinessResponse,
)
from src.app.services import ResourceService

router = APIRouter(tags=["resources"])


@router.get("/resources/status", response_model=ResourceStatusListResponse)
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


@router.get("/runtime/resources", response_model=RuntimeResourcesResponse)
def get_runtime_resources(
    svc: ResourceService = Depends(resource_service),
):
    return RuntimeResourcesResponse(resources=svc.get_runtime_resources())


@router.get("/runtime/capabilities", response_model=RuntimeCapabilitiesResponse)
def get_runtime_capabilities(
    svc: ResourceService = Depends(resource_service),
):
    data = svc.get_runtime_capabilities()
    return RuntimeCapabilitiesResponse(
        resources=data["resources"],
        checks=[
            ResourceStatusResponse(
                name=item["name"],
                available=item["available"],
                detail=item["detail"],
                metadata=item["metadata"],
            )
            for item in data["checks"]
        ],
    )


@router.post("/runtime/check-task-readiness", response_model=TaskReadinessResponse)
def check_task_readiness(
    body: TaskReadinessRequest,
    svc: ResourceService = Depends(resource_service),
):
    data = svc.check_task_readiness(
        task_type=body.task_type,
        execution_profile=body.execution_profile,
        input_path=body.input_path,
    )
    return TaskReadinessResponse(**data)
