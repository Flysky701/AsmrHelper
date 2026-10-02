"""Pipeline preset routes; no execution service is initialized here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.api.http.dependencies import preset_catalog_service
from src.api.http.schemas.pipeline import (
    PipelinePresetsResponse,
    PresetCopyRequest,
    PresetCreateRequest,
    PresetItem,
    PresetUpdateRequest,
    PresetRestoreRequest,
    GraphPresetItem,
    GraphPresetCreateRequest,
    GraphPresetUpdateRequest,
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
def list_presets(include_graph: bool = False, svc: PresetCatalogService = Depends(preset_catalog_service)):
    # Existing clients only understand stages/outputs. One catalog, versioned views.
    presets = _call(svc.list_presets)
    return PipelinePresetsResponse(presets=[p for p in presets if include_graph or p.get("version") != 2])


@router.get("/presets/archived", response_model=PipelinePresetsResponse)
def list_archived_presets(include_graph: bool = False, svc: PresetCatalogService = Depends(preset_catalog_service)):
    presets = _call(svc.list_archived_presets)
    return PipelinePresetsResponse(presets=[p for p in presets if include_graph or p.get("version") != 2])


@router.get("/graph-capabilities")
def graph_capabilities():
    from src.core.orchestration.pipeline.graph_catalog import capabilities
    return {"version": 2, "capabilities": capabilities(), "execution": "topological-serial",
            "partial_resume": False}


@router.post("/presets", response_model=GraphPresetItem | PresetItem, status_code=201)
def create_preset(
    body: GraphPresetCreateRequest | PresetCreateRequest, svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.create_preset, body.model_dump(exclude_none=True))


@router.get("/presets/{preset_id}/graph-draft")
def graph_draft(preset_id: str, svc: PresetCatalogService = Depends(preset_catalog_service)):
    return _call(svc.graph_draft, preset_id)


@router.post("/presets/{preset_id}/copy", response_model=GraphPresetItem | PresetItem, status_code=201)
def copy_preset(
    preset_id: str, body: PresetCopyRequest,
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.copy_preset, preset_id, body.label)


@router.put("/presets/{preset_id}", response_model=GraphPresetItem | PresetItem)
def update_preset(
    preset_id: str, body: GraphPresetUpdateRequest | PresetUpdateRequest,
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.update_preset, preset_id, body.model_dump(exclude={"revision"}, exclude_none=True), body.revision)


@router.delete("/presets/{preset_id}", status_code=204, response_class=Response)
def delete_preset(
    preset_id: str, revision: int = Query(..., ge=1),
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    _call(svc.delete_preset, preset_id, revision)
    return Response(status_code=204)


@router.post("/presets/{preset_id}/restore", response_model=GraphPresetItem | PresetItem)
def restore_preset(
    preset_id: str, body: PresetRestoreRequest,
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    return _call(svc.restore_preset, preset_id, body.revision, body.label)
