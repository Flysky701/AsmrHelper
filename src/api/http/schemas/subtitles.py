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


class ScriptToVttRequest(BaseModel):
    script_path: str = Field(..., description="Path to the script file")
    output_path: str = Field("", description="Output subtitle file path")
    audio_path: str | None = Field(None, description="Optional audio file for alignment")
    vtt_path: str | None = Field(None, description="Existing VTT file for re-alignment")
    fmt: str = Field("vtt", description="Output format (vtt/srt/lrc)")
    use_llm_clean: bool = Field(True, description="Use LLM to clean script text")
    asr_model_size: str = Field("large-v3", description="ASR model size")
    asr_language: str = Field("ja", description="Audio language")
    track_index: int | None = Field(None, description="Audio track index")
    vertical_mode: str = Field("auto", description="Vertical text mode (auto/horizontal/vertical)")
    debug_dir: str | None = Field(None, description="Debug output directory")


class ScriptToVttResponse(BaseModel):
    mode: str
    output_path: str | None = None
    text: str = ""
    line_count: int = 0
