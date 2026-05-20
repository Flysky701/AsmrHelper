"""Schemas for input asset endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InspectInputsRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class InputAssetResponse(BaseModel):
    asset_id: str
    absolute_path: str
    kind: str
    display_name: str = ""
    extension: str = ""
    exists: bool = False
    readable: bool = False
    size_bytes: int = 0
    warnings: list[str] = Field(default_factory=list)


class InspectInputsResponse(BaseModel):
    assets: list[InputAssetResponse] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DiscoverCompanionsRequest(BaseModel):
    asset_id: str


class DiscoverCompanionsResponse(BaseModel):
    primary_asset_id: str
    suggested_companions: list[InputAssetResponse] = Field(default_factory=list)
