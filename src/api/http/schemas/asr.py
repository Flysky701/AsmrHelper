"""Pydantic schemas for ASR endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .capabilities import CapabilityOptionResponse
from .subtitles import SubtitleSegmentModel


class TranscribeRequest(BaseModel):
    input_path: str = Field(..., description="Path to audio file")
    output_path: str | None = Field(None, description="Path to save transcription output")
    provider: str = Field("faster_whisper", description="ASR provider id")
    model: str | None = Field(None, description="Provider-specific model id")
    language: str = Field("ja", description="Language code (ja/zh/en)")
    common_options: dict[str, Any] = Field(default_factory=dict, description="Optional common runtime options")
    provider_options: dict[str, Any] = Field(default_factory=dict, description="Optional provider-specific options")


class TranscribeResponse(BaseModel):
    segments: list[SubtitleSegmentModel] = Field(default_factory=list)
    output_path: str | None = None
    text: str = ""


class AsrEngineDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    kind: str
    supported_models: list[str] = Field(default_factory=list)
    default_model: str
    common_option_schema: list[CapabilityOptionResponse] = Field(default_factory=list)
    provider_option_schema: list[CapabilityOptionResponse] = Field(default_factory=list)
    supports: dict[str, Any] = Field(default_factory=dict)


class AsrEngineListResponse(BaseModel):
    engines: list[AsrEngineDescriptorResponse] = Field(default_factory=list)
