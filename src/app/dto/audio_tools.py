"""DTOs for audio tool operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# --- Vocal Separation ---


@dataclass(slots=True)
class SeparationRequest:
    input_path: str
    output_dir: str = ""
    model: str = "htdemucs"
    stems: Optional[list[str]] = None


@dataclass(slots=True)
class SeparationResult:
    input_path: str
    stems: dict[str, str] = field(default_factory=dict)
    primary_output: Optional[str] = None


# --- Audio Format Conversion ---


@dataclass(slots=True)
class ConvertRequest:
    input_path: str
    output_path: str
    target_format: str = "wav"
    sample_rate: int = 44100
    channels: int = 2


@dataclass(slots=True)
class ConvertResult:
    input_path: str
    output_path: str
    format: str
    sample_rate: int
    channels: int
    duration: float = 0.0


# --- Subtitle-based Audio Splitting ---


@dataclass(slots=True)
class SplitRequest:
    audio_path: str
    subtitle_path: str
    output_dir: str
    padding: float = 0.1


@dataclass(slots=True)
class SplitSegment:
    index: int
    start: float
    end: float
    text: str
    output_path: str


@dataclass(slots=True)
class SplitResult:
    audio_path: str
    subtitle_path: str
    segments: list[SplitSegment] = field(default_factory=list)
    total_segments: int = 0


# --- Subtitle Translation (with timestamps) ---


@dataclass(slots=True)
class SubtitleTranslationRequest:
    input_path: str
    output_path: str = ""
    provider: str = "deepseek"
    source_lang: str = "ja"
    target_lang: str = "zh"
    bilingual: bool = True


@dataclass(slots=True)
class SubtitleTranslationResult:
    input_path: str
    output_path: Optional[str] = None
    total_segments: int = 0
    provider: str = ""
    source_lang: str = ""
    target_lang: str = ""


# --- Volume Preview ---


@dataclass(slots=True)
class VolumePreviewRequest:
    audio_path: str
    tts_path: Optional[str] = None
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5


@dataclass(slots=True)
class VolumePreviewResult:
    audio_path: str
    rms_volume: float = 0.0
    tts_rms_volume: Optional[float] = None
    recommended_original_volume: float = 0.85
    recommended_tts_ratio: float = 0.5
