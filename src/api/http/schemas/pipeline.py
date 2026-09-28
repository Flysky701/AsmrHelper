"""Pydantic schemas for pipeline endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

class PresetItem(BaseModel):
    id: str
    label: str
    description: str
    stages: list[str] = Field(default_factory=list)


class PipelinePresetsResponse(BaseModel):
    presets: list[PresetItem]
