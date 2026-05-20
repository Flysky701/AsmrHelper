"""Pydantic schemas for TTS endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    input_path: str = Field(..., description="Path to text file")
    output_path: str = Field(..., description="Path to save audio output")
    engine: str = Field("edge", description="TTS engine (edge/qwen3)")
    voice: str = Field("zh-CN-XiaoxiaoNeural", description="Voice name")


class SynthesizeResponse(BaseModel):
    engine: str
    voice: str
    output_path: str


class TtsEngineDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    models: list[str] = Field(default_factory=list)
    common_options: list[dict[str, Any]] = Field(default_factory=list)
    provider_options: list[dict[str, Any]] = Field(default_factory=list)
    supports: dict[str, Any] = Field(default_factory=dict)


class TtsEngineListResponse(BaseModel):
    engines: list[TtsEngineDescriptorResponse] = Field(default_factory=list)
