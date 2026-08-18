"""Pydantic schemas for voice endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceProfileSummaryResponse(BaseModel):
    id: str
    name: str
    category: str
    engine: str
    description: str
    available: bool = False


class VoiceProfileResponse(BaseModel):
    id: str
    name: str
    category: str
    engine: str
    description: str
    speaker: str = ""
    instruct: str = ""
    design_instruct: str = ""
    ref_audio: str = ""
    generated: bool = False
    available: bool = False


class VoiceDesignRequest(BaseModel):
    description: str = Field(..., description="Natural language voice description")
    name: str = Field(..., description="Display name for the new voice")
    ref_text: str = Field("", description="Reference text for synthesis")


class VoiceCloneRequest(BaseModel):
    audio_path: str = Field(..., description="Path to reference audio file")
    name: str = Field(..., description="Display name for the new voice")
    ref_text: str = Field(
        "",
        description="Exact reference transcript; required for ICL cloning",
    )
    x_vector_only_mode: bool = Field(
        False,
        description="Use only the speaker embedding for cross-language cloning",
    )


class SegmentAnalyzeRequest(BaseModel):
    audio_path: str = Field(..., description="Path to audio file")
    subtitle_path: str | None = Field(None, description="Optional subtitle file")
    audio_language: str = Field("ja", description="Audio language code")


class SegmentInfoResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    duration: float
    score: int = 0
    label: str = ""
    details: dict = Field(default_factory=dict)


class SegmentAnalyzeResponse(BaseModel):
    audio_path: str
    mode: str = ""
    segments: list[SegmentInfoResponse] = Field(default_factory=list)
    recommended_indices: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# Generation routes reuse the shared task-status response schema.
class VoicePreviewRequest(BaseModel):
    text: str = Field("", description="Text to synthesize")
    speed: float = Field(1.0, description="Speech speed")
    language: str = Field("auto", description="Target synthesis language")
