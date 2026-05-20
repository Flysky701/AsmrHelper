"""Pydantic schemas for ASR endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .subtitles import SubtitleSegmentModel


class TranscribeRequest(BaseModel):
    input_path: str = Field(..., description="Path to audio file")
    output_path: str | None = Field(None, description="Path to save transcription output")
    model: str = Field("base", description="ASR model size (tiny/base/small/medium/large-v3)")
    language: str = Field("ja", description="Language code (ja/zh/en)")


class TranscribeResponse(BaseModel):
    segments: list[SubtitleSegmentModel] = Field(default_factory=list)
    output_path: str | None = None
    text: str = ""


class AsrEngineDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    models: list[str] = Field(default_factory=list)
    common_options: list[dict[str, Any]] = Field(default_factory=list)
    provider_options: list[dict[str, Any]] = Field(default_factory=list)
    supports: dict[str, Any] = Field(default_factory=dict)


class AsrEngineListResponse(BaseModel):
    engines: list[AsrEngineDescriptorResponse] = Field(default_factory=list)
