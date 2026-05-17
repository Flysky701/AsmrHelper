"""Pydantic schemas for ASR endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscribeRequest(BaseModel):
    input_path: str = Field(..., description="Path to audio file")
    output_path: str | None = Field(None, description="Path to save transcription output")
    model: str = Field("base", description="ASR model size (tiny/base/small/medium/large-v3)")
    language: str = Field("ja", description="Language code (ja/zh/en)")


class SubtitleSegmentResponse(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    segments: list[SubtitleSegmentResponse] = Field(default_factory=list)
    output_path: str | None = None
    text: str = ""
