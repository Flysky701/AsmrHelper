"""Settings management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.api.http.dependencies import settings_service
from src.api.http.schemas.settings import (
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderModelsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SettingsValidateRequest,
    SettingsValidateResponse,
    ConnectionRemovalRequest,
)
from src.app.services import SettingsService
from src.app.services.settings_service import ProviderModelsError

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/connections/{connection_id}/removal-preview")
def connection_removal_preview(connection_id: str, svc: SettingsService = Depends(settings_service)):
    return svc.connection_removal_preview(connection_id)


@router.post("/connections/{connection_id}/removal", response_model=SettingsResponse)
def set_connection_removed(connection_id: str, body: ConnectionRemovalRequest,
                           svc: SettingsService = Depends(settings_service)):
    return SettingsResponse(settings=svc.set_connection_removed(connection_id, **body.model_dump()))


@router.post("/models", response_model=ProviderModelsResponse)
def discover_models(
    body: ProviderTestRequest,
    svc: SettingsService = Depends(settings_service),
):
    try:
        models = svc.discover_models(body.provider, body.settings or None)
    except ProviderModelsError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )
    return ProviderModelsResponse(provider=body.provider, models=models)


@router.get("", response_model=SettingsResponse)
def get_settings(
    svc: SettingsService = Depends(settings_service),
):
    return SettingsResponse(settings=svc.get_settings(masked=True))


@router.put("", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    svc: SettingsService = Depends(settings_service),
):
    updated = svc.update_settings(body.settings)
    return SettingsResponse(settings=updated)


@router.post("/validate", response_model=SettingsValidateResponse)
def validate_settings(
    body: SettingsValidateRequest | None = None,
    svc: SettingsService = Depends(settings_service),
):
    valid, errors, masked_settings = svc.validate_settings(body.settings if body else None)
    return SettingsValidateResponse(
        valid=valid,
        errors=errors,
        settings=masked_settings,
    )


@router.post("/test-provider", response_model=ProviderTestResponse)
def test_provider(
    body: ProviderTestRequest,
    svc: SettingsService = Depends(settings_service),
):
    result = svc.test_provider(body.provider, body.settings or None)
    return ProviderTestResponse(
        provider=result.provider,
        success=result.success,
        error_code=result.error_code,
        message=result.message,
        errors=[] if result.success else [result.message],
    )
