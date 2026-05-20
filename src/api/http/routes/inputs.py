"""Input asset routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import input_catalog_service
from src.api.http.schemas.inputs import (
    DiscoverCompanionsRequest,
    DiscoverCompanionsResponse,
    InputAssetResponse,
    InspectInputsRequest,
    InspectInputsResponse,
)
from src.app.services import InputCatalogService

router = APIRouter(prefix="/inputs", tags=["inputs"])


def _to_asset_response(asset) -> InputAssetResponse:
    return InputAssetResponse(
        asset_id=asset.asset_id,
        absolute_path=asset.absolute_path,
        kind=asset.kind,
        display_name=asset.display_name,
        extension=asset.extension,
        exists=asset.exists,
        readable=asset.readable,
        size_bytes=asset.size_bytes,
        warnings=asset.warnings,
    )


@router.post("/inspect", response_model=InspectInputsResponse)
def inspect_inputs(
    body: InspectInputsRequest,
    svc: InputCatalogService = Depends(input_catalog_service),
):
    assets = svc.inspect_paths(body.paths)
    return InspectInputsResponse(
        assets=[_to_asset_response(asset) for asset in assets],
        errors=[],
        warnings=[],
    )


@router.post("/discover-companions", response_model=DiscoverCompanionsResponse)
def discover_companions(
    body: DiscoverCompanionsRequest,
    svc: InputCatalogService = Depends(input_catalog_service),
):
    companions = svc.discover_companions(body.asset_id)
    return DiscoverCompanionsResponse(
        primary_asset_id=body.asset_id,
        suggested_companions=[_to_asset_response(asset) for asset in companions],
    )
