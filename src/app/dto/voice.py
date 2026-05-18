"""DTOs for voice profile and design operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class VoiceProfileSummary:
    id: str
    name: str
    category: str
    engine: str
    description: str
    available: bool = False


@dataclass(slots=True)
class VoiceProfileView:
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


@dataclass(slots=True)
class VoiceDesignRequest:
    description: str
    name: str
    ref_text: str = ""


@dataclass(slots=True)
class VoiceDesignResult:
    profile_id: str
    name: str
    category: str
    ref_audio_path: str = ""
    prompt_cache_path: str = ""


@dataclass(slots=True)
class VoiceCloneRequest:
    audio_path: str
    name: str
    ref_text: str = ""


@dataclass(slots=True)
class VoiceCloneResult:
    profile_id: str
    name: str
    category: str
    ref_audio_path: str = ""
    prompt_cache_path: str = ""


@dataclass(slots=True)
class SegmentAnalyzeRequest:
    audio_path: str
    subtitle_path: Optional[str] = None
    audio_language: str = "ja"


@dataclass(slots=True)
class SegmentInfo:
    index: int
    start: float
    end: float
    text: str
    duration: float
    score: int = 0
    label: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SegmentAnalyzeResult:
    audio_path: str
    mode: str = ""
    segments: list[SegmentInfo] = field(default_factory=list)
    recommended_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VoicePreviewRequest:
    profile_id: str
    text: str = ""
    speed: float = 1.0


@dataclass(slots=True)
class VoicePreviewResult:
    profile_id: str
    audio_path: str = ""
