"""Pydantic schemas for pipeline endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PresetItem(BaseModel):
    id: str
    label: str
    description: str
    stages: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    revision: int = 1
    builtin: bool = True


class PipelinePresetsResponse(BaseModel):
    presets: list[PresetItem]


class PresetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    stages: list[str] = Field(min_length=1, max_length=7)
    outputs: list[str] = Field(min_length=1, max_length=7)


class PresetUpdateRequest(PresetCreateRequest):
    revision: int = Field(ge=1)


class PresetCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str = Field(min_length=1, max_length=100)
