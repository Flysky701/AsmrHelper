"""Pydantic schemas for TTS endpoints."""

from __future__ import annotations

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
