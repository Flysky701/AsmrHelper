"""Pydantic schemas for TTS endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .capabilities import CapabilityOptionResponse


class SynthesizeRequest(BaseModel):
    input_path: str = Field(..., description="Path to text file")
    output_path: str = Field(..., description="Path to save audio output")
    engine: str = Field("edge", description="TTS engine (edge/qwen3)")
    model: str | None = Field(None, description="Optional model identifier")
    voice: str | None = Field(None, description="Voice name")
    speed: float | None = Field(None, description="Optional synthesis speed")
    common_options: dict[str, Any] = Field(default_factory=dict, description="Optional common runtime options")
    provider_options: dict[str, Any] = Field(default_factory=dict, description="Optional provider-specific options")


class SynthesizeResponse(BaseModel):
    engine: str
    voice: str
    output_path: str


class TtsEngineDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    kind: str
    supported_models: list[str] = Field(default_factory=list)
    default_model: str
    common_option_schema: list[CapabilityOptionResponse] = Field(default_factory=list)
    provider_option_schema: list[CapabilityOptionResponse] = Field(default_factory=list)
    supports: dict[str, Any] = Field(default_factory=dict)


class TtsEngineListResponse(BaseModel):
    engines: list[TtsEngineDescriptorResponse] = Field(default_factory=list)
