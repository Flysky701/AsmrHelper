"""Settings management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import settings_service
from src.api.http.schemas.settings import (
    SettingsResponse,
    SettingsUpdateRequest,
    SettingsValidateRequest,
    SettingsValidateResponse,
)
from src.app.services import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings(
    svc: SettingsService = Depends(settings_service),
):
    return SettingsResponse(settings=svc.get_settings(masked=True))


@router.get("/effective", response_model=SettingsResponse)
def get_effective_settings(
    svc: SettingsService = Depends(settings_service),
):
    return SettingsResponse(settings=svc.get_effective_settings(masked=True))


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
