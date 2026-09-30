"""Pipeline preset routes; no execution service is initialized here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.http.dependencies import preset_catalog_service
from src.api.http.schemas.pipeline import (
    PipelinePresetsResponse,
    PresetCopyRequest,
    PresetCreateRequest,
    PresetItem,
    PresetUpdateRequest,
)
from src.app.services.preset_catalog_service import (
    BuiltinPresetError,
    PresetCatalogService,
    PresetConflictError,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _call(fn, *args):
    try:
        return fn(*args)
    except PresetConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except BuiltinPresetError as exc:
        raise HTTPException(403, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Preset does not exist") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, "Preset storage is unavailable; existing presets were not replaced") from exc


@router.get("/presets", response_model=PipelinePresetsResponse)
def list_presets(svc: PresetCatalogService = Depends(preset_catalog_service)):
    return PipelinePresetsResponse(presets=[PresetItem(**p) for p in _call(svc.list_presets)])


@router.post("/presets", response_model=PresetItem, status_code=201)
def create_preset(
    body: PresetCreateRequest, svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.create_preset, body.model_dump())


@router.post("/presets/{preset_id}/copy", response_model=PresetItem, status_code=201)
def copy_preset(
    preset_id: str, body: PresetCopyRequest,
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.copy_preset, preset_id, body.label)


@router.put("/presets/{preset_id}", response_model=PresetItem)
def update_preset(
    preset_id: str, body: PresetUpdateRequest,
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.update_preset, preset_id, body.model_dump(exclude={"revision"}), body.revision)
