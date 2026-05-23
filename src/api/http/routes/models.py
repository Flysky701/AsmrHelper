"""Model management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.http.dependencies import model_service
from src.api.http.schemas.models import (
    ModelInstallAsyncResponse,
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
            supports_install=m.supports_install,
            supports_remove=m.supports_remove,
            family_id=m.family_id,
            variant_group=m.variant_group,
            variant_tier=m.variant_tier,
            is_primary_variant=m.is_primary_variant,
            dependency_group=m.dependency_group,
            runtime_profile=m.runtime_profile,
            preferred_runtime=m.preferred_runtime,
            install_modes=m.install_modes,
            default_install_mode=m.default_install_mode,
            required_assets=m.required_assets,
            recommended_assets=m.recommended_assets,
            required_system_tools=m.required_system_tools,
            supported_os=m.supported_os,
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


@router.post("/{model_id}/install")
def install_model(
    model_id: str,
    body: ModelInstallRequest | None = None,
    sync: bool = Query(False, description="Synchronous install (blocking). Default is async."),
    svc: ModelService = Depends(model_service),
):
    mirror = body.mirror if body else None
    force = body.force if body else False
    install_mode = body.install_mode if body else "single"
    install_dependencies = body.install_dependencies if body else True
    install_recommended_assets = body.install_recommended_assets if body else False
    allow_fallback_variant = body.allow_fallback_variant if body else False

    if sync:
        result = svc.install_model(
            model_id,
            mirror=mirror,
            force=force,
            install_mode=install_mode,
            install_dependencies=install_dependencies,
            install_recommended_assets=install_recommended_assets,
            allow_fallback_variant=allow_fallback_variant,
        )
        return ModelOperationResponse(
            action=result.action,
            model_id=result.model_id,
            success=result.success,
            status=result.status,
            detail=result.detail,
        )

    task_id = svc.install_model_async(
        model_id,
        mirror=mirror,
        force=force,
        install_mode=install_mode,
        install_dependencies=install_dependencies,
        install_recommended_assets=install_recommended_assets,
        allow_fallback_variant=allow_fallback_variant,
    )
    return ModelInstallAsyncResponse(task_id=task_id, status="pending")


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


@router.post("/{model_id}/unload", response_model=ModelOperationResponse)
def unload_model(
    model_id: str,
    svc: ModelService = Depends(model_service),
):
    result = svc.unload_model(model_id)
    return ModelOperationResponse(
        action=result.action,
        model_id=result.model_id,
        success=result.success,
        status=result.status,
        detail=result.detail,
    )


@router.post("/unload-all", status_code=204)
def unload_all_models(
    svc: ModelService = Depends(model_service),
):
    svc.unload_all_models()
