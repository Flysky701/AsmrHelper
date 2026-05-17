"""Model management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import model_service
from src.api.http.schemas.models import (
    ModelInstallRequest,
    ModelOperationResponse,
    ModelStatusResponse,
    ModelSummaryResponse,
    ModelVerificationResponse,
)
from src.app.services import ModelService

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelSummaryResponse])
def list_models(
    kind: str | None = None,
    category: str | None = None,
    svc: ModelService = Depends(model_service),
):
    models = svc.list_models(kind=kind, category=category)
    return [
        ModelSummaryResponse(
            model_id=m.model_id,
            kind=m.kind,
            category=m.category,
            backend=m.backend,
            display_name=m.display_name,
        )
        for m in models
    ]


@router.get("/statuses", response_model=list[ModelStatusResponse])
def list_model_statuses(
    kind: str | None = None,
    category: str | None = None,
    svc: ModelService = Depends(model_service),
):
    statuses = svc.list_model_statuses(kind=kind, category=category)
    return [
        ModelStatusResponse(
            model_id=s.model_id,
            status=s.status,
            detail=s.detail,
        )
        for s in statuses
    ]


@router.get("/{model_id}/status", response_model=ModelStatusResponse)
def get_model_status(
    model_id: str,
    svc: ModelService = Depends(model_service),
):
    status = svc.get_model_status(model_id)
    return ModelStatusResponse(
        model_id=status.model_id,
        status=status.status,
        detail=status.detail,
    )


@router.post("/{model_id}/install", response_model=ModelOperationResponse)
def install_model(
    model_id: str,
    body: ModelInstallRequest | None = None,
    svc: ModelService = Depends(model_service),
):
    mirror = body.mirror if body else None
    force = body.force if body else False
    result = svc.install_model(model_id, mirror=mirror, force=force)
    return ModelOperationResponse(
        action=result.action,
        model_id=result.model_id,
        success=result.success,
        status=result.status,
        detail=result.detail,
    )


@router.post("/{model_id}/verify", response_model=list[ModelVerificationResponse])
def verify_model(
    model_id: str,
    svc: ModelService = Depends(model_service),
):
    results = svc.verify_models(model_id=model_id)
    return [
        ModelVerificationResponse(
            model_id=r.model_id,
            success=r.success,
            status=r.status,
            detail=r.detail,
        )
        for r in results
    ]


@router.delete("/{model_id}", response_model=ModelOperationResponse)
def remove_model(
    model_id: str,
    svc: ModelService = Depends(model_service),
):
    result = svc.remove_model(model_id)
    return ModelOperationResponse(
        action=result.action,
        model_id=result.model_id,
        success=result.success,
        status=result.status,
        detail=result.detail,
    )
