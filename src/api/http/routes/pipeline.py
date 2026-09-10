"""Pipeline routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import preset_catalog_service
from src.api.http.schemas.pipeline import (
    PipelinePresetsResponse,
    PresetItem,
)
from src.app.services import PresetCatalogService

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/presets", response_model=PipelinePresetsResponse)
def list_presets(
    svc: PresetCatalogService = Depends(preset_catalog_service),
):
    raw = svc.list_presets()
    return PipelinePresetsResponse(
        presets=[
            PresetItem(
                id=p["id"],
                label=p["label"],
                description=p.get("description", ""),
                stages=p.get("stages", []),
            )
            for p in raw
        ]
    )
