"""Model management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from src.api.http.dependencies import model_service
from src.api.http.schemas.tasks import TaskStatusResponse
from src.api.http.schemas.models import (
    ModelInstallRequest,
    ModelDownloadRequest,
    ModelOperationResponse,
    ModelStatusIssueResponse,
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
            capability_models=m.capability_models,
            estimated_size_mb=m.estimated_size_mb,
            install_strategy=m.install_strategy,
            supports_install=m.supports_install,
            supports_remove=m.supports_remove,
            family_id=m.family_id,
            variant_group=m.variant_group,
            variant_tier=m.variant_tier,
            is_primary_variant=m.is_primary_variant,
            is_auxiliary=m.is_auxiliary,
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
            executable=s.executable,
            path=s.path, weights_ready=s.weights_ready, runtime_ready=s.runtime_ready, shared_readonly=s.shared_readonly,
            issues=[
                {
                    "code": issue.code,
                    "requirement": issue.requirement,
                    "message": issue.message,
                }
                for issue in s.issues
            ],
        )
        for s in statuses
    ]


@router.get("/sources")
def list_model_sources():
    from src.core.resources.model_assets import sources
    return {"roots": sources(), "readonly": True}


@router.post("/sources/remove")
def unlink_model_source(body: dict):
    from src.core.resources.model_assets import remove_source, sources
    from src.app.errors import AppValidationError
    value = body.get("path")
    if not isinstance(value, str) or not value.strip():
        raise AppValidationError("请选择要解除引用的模型目录")
    try:
        remove_source(value)
    except (ValueError, OSError) as exc:
        raise AppValidationError(str(exc)) from exc
    return {"roots": sources(), "readonly": True}


@router.post("/sources")
def add_model_source(body: dict, svc: ModelService = Depends(model_service)):
    from src.core.resources.model_assets import add_source, sources
    from src.app.errors import AppValidationError
    try:
        add_source(str(body.get("path", "")))
    except (ValueError, OSError) as exc:
        raise AppValidationError(str(exc)) from exc
    return {"roots": sources(), "readonly": True}


@router.post("/scan")
def scan_model_sources(svc: ModelService = Depends(model_service)):
    from src.core.resources.model_assets import scan_roots, candidates, complete, add_source
    from src.config import PROJECT_ROOT
    from pathlib import Path
    roots = scan_roots()
    found = []
    for entry in svc.core_service.list_models(kind="local"):
        for root in roots:
            for path in candidates(entry, [root]):
                if complete(entry, path):
                    if Path(root).resolve() != (PROJECT_ROOT / 'models').resolve():
                        add_source(root)
                    found.append({"model_id": entry.id, "path": str(path), "complete": True, "readonly": True})
                    break
    return {"found": found, "roots": roots}


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
        executable=status.executable,
        path=status.path, weights_ready=status.weights_ready, runtime_ready=status.runtime_ready, shared_readonly=status.shared_readonly,
        issues=[
            {
                "code": issue.code,
                "requirement": issue.requirement,
                "message": issue.message,
            }
            for issue in status.issues
        ],
    )


@router.post(
    "/{model_id}/install",
    response_model=ModelOperationResponse | TaskStatusResponse,
)
def install_model(
    model_id: str,
    response: Response,
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

    task = svc.install_model_async(
        model_id,
        mirror=mirror,
        force=force,
        install_mode=install_mode,
        install_dependencies=install_dependencies,
        install_recommended_assets=install_recommended_assets,
        allow_fallback_variant=allow_fallback_variant,
    )
    response.status_code = 201
    return TaskStatusResponse.from_task_status(task)


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
            issues=[
                ModelStatusIssueResponse(
                    code=issue.code,
                    requirement=issue.requirement,
                    message=issue.message,
                )
                for issue in r.issues
            ],
        )
        for r in results
    ]


@router.delete("/{model_id}", response_model=ModelOperationResponse)
def remove_model(
    model_id: str,
    token: str = Query(""),
    confirmed: bool = Query(False),
    svc: ModelService = Depends(model_service),
):
    from src.app.services.model_removal_service import ModelRemovalService
    from src.app.errors import AppValidationError
    try:
        result = ModelRemovalService(svc).execute(model_id, token, confirmed)
    except (ValueError, OSError) as exc:
        raise AppValidationError(str(exc)) from exc
    return ModelOperationResponse(
        action=result.action,
        model_id=result.model_id,
        success=result.success,
        status=result.status,
        detail=result.detail,
    )


@router.post("/{model_id}/deletion-preview")
def model_deletion_preview(model_id: str, svc: ModelService = Depends(model_service)):
    from src.app.services.model_removal_service import ModelRemovalService
    from src.app.errors import AppValidationError
    try:
        return ModelRemovalService(svc).preview(model_id)
    except (ValueError, OSError) as exc:
        raise AppValidationError(str(exc)) from exc


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


@router.post("/{model_id}/runtime", response_model=TaskStatusResponse, status_code=201)
def prepare_model_runtime(model_id: str, svc: ModelService = Depends(model_service)):
    return TaskStatusResponse.from_task_status(svc.install_model_async(model_id, operation="runtime"))


@router.post("/{model_id}/download", response_model=TaskStatusResponse, status_code=201)
def download_model_weights(model_id: str, body: ModelDownloadRequest | None = None,
                           svc: ModelService = Depends(model_service)):
    options = body or ModelDownloadRequest()
    return TaskStatusResponse.from_task_status(svc.install_model_async(
        model_id, mirror=options.mirror, force=options.force, install_mode=options.install_mode,
        install_dependencies=False, install_recommended_assets=options.install_recommended_assets,
        allow_fallback_variant=False, operation="download"))
