"""Pydantic schemas for subtitle endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SubtitleSegmentResponse(BaseModel):
    start: float
    end: float
    text: str


class SubtitleLoadRequest(BaseModel):
    file_path: str = Field(..., description="Path to the subtitle file to load")


class SubtitleLoadResponse(BaseModel):
    segments: list[SubtitleSegmentResponse] = Field(default_factory=list)


class SubtitleExportRequest(BaseModel):
    segments: list[SubtitleSegmentResponse] = Field(..., description="Subtitle segments to export")
    output_path: str = Field(..., description="Path to save SRT file")


class SubtitleExportResponse(BaseModel):
    output_path: str
    segment_count: int
