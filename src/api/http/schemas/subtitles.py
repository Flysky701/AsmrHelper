"""Pydantic schemas for subtitle endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class SubtitleSegmentModel(BaseModel):
    start: float
    end: float
    text: str


class SubtitleDocumentModel(BaseModel):
    segments: list[SubtitleSegmentModel] = Field(default_factory=list)


class SubtitleLoadRequest(BaseModel):
    file_path: str = Field(..., description="Path to the subtitle file to load")


class SubtitleLoadResponse(BaseModel):
    document: SubtitleDocumentModel
    segments: list[SubtitleSegmentModel] = Field(default_factory=list)


class SubtitleExportRequest(BaseModel):
    document: Optional[SubtitleDocumentModel] = None
    segments: list[SubtitleSegmentModel] = Field(default_factory=list)
    output_path: str = Field(..., description="Path to save SRT file")

    @model_validator(mode="after")
    def validate_document_input(self) -> "SubtitleExportRequest":
        if self.document is None and not self.segments:
            raise ValueError("either document or segments is required")
        return self

    def resolved_document(self) -> SubtitleDocumentModel:
        if self.document is not None:
            return self.document
        return SubtitleDocumentModel(segments=self.segments)


class SubtitleExportResponse(BaseModel):
    output_path: str
    segment_count: int
