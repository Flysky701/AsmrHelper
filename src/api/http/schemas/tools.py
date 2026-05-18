"""Pydantic schemas for audio tool endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SeparationRequest(BaseModel):
    input_path: str = Field(..., description="Path to input audio file")
    output_dir: str = Field("", description="Output directory")
    model: str = Field("htdemucs", description="Separation model name")
    stems: list[str] | None = Field(None, description="Stems to extract (default: vocals only)")


class SeparationResponse(BaseModel):
    input_path: str
    stems: dict[str, str] = Field(default_factory=dict)
    primary_output: str | None = None


class ConvertRequest(BaseModel):
    input_path: str = Field(..., description="Path to input audio file")
    output_path: str = Field(..., description="Path for output file")
    target_format: str = Field("wav", description="Target audio format")
    sample_rate: int = Field(44100, description="Target sample rate")
    channels: int = Field(2, description="Target channel count")


class ConvertResponse(BaseModel):
    input_path: str
    output_path: str
    format: str
    sample_rate: int
    channels: int
    duration: float = 0.0


class SplitRequest(BaseModel):
    audio_path: str = Field(..., description="Path to audio file")
    subtitle_path: str = Field(..., description="Path to subtitle file")
    output_dir: str = Field(..., description="Output directory for segments")
    padding: float = Field(0.1, description="Padding in seconds around each segment")


class SplitSegmentResponse(BaseModel):
    index: int
    start: float
    end: float
    text: str
    output_path: str


class SplitResponse(BaseModel):
    audio_path: str
    subtitle_path: str
    segments: list[SplitSegmentResponse] = Field(default_factory=list)
    total_segments: int = 0


class SubtitleTranslationRequest(BaseModel):
    input_path: str = Field(..., description="Path to subtitle file")
    output_path: str = Field("", description="Output path (default: auto-generated)")
    provider: str = Field("deepseek", description="Translation provider")
    source_lang: str = Field("ja", description="Source language code")
    target_lang: str = Field("zh", description="Target language code")
    bilingual: bool = Field(True, description="Output bilingual subtitle")


class SubtitleTranslationResponse(BaseModel):
    input_path: str
    output_path: str | None = None
    total_segments: int = 0
    provider: str = ""
    source_lang: str = ""
    target_lang: str = ""


class VolumePreviewRequest(BaseModel):
    audio_path: str = Field(..., description="Path to audio file")
    tts_path: str | None = Field(None, description="Optional TTS audio for comparison")
    original_volume: float = Field(0.85, description="Original volume level")
    tts_volume_ratio: float = Field(0.5, description="TTS volume ratio")


class VolumePreviewResponse(BaseModel):
    audio_path: str
    rms_volume: float = 0.0
    tts_rms_volume: float | None = None
    recommended_original_volume: float = 0.85
    recommended_tts_ratio: float = 0.5
