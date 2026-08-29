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
    task_id: str = ""
    ref_audio_path: str = ""
    prompt_cache_path: str = ""


@dataclass(slots=True)
class VoiceCloneRequest:
    audio_path: str
    name: str
    ref_text: str = ""
    x_vector_only_mode: bool = False
    analysis_id: str = ""
    candidate_id: str = ""
    confirmed_text: str = ""


@dataclass(slots=True)
class VoiceCloneResult:
    profile_id: str
    name: str
    category: str
    task_id: str = ""
    ref_audio_path: str = ""
    prompt_cache_path: str = ""


@dataclass(slots=True)
class SegmentAnalyzeRequest:
    audio_path: str
    subtitle_path: Optional[str] = None
    audio_language: str = "ja"
    separate_vocals: bool = False
    x_vector_only_mode: bool = False


@dataclass(slots=True)
class SegmentInfo:
    index: int
    start: float
    end: float
    text: str
    duration: float
    score: int = 0
    label: str = ""
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VoiceCloneCandidate:
    candidate_id: str
    source_variant: str
    start: float
    end: float
    text: str
    score: int = 0
    label: str = ""
    eligible: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    preview_audio_path: str = ""


@dataclass(slots=True)
class SegmentAnalyzeResult:
    audio_path: str
    mode: str = ""
    segments: list[SegmentInfo] = field(default_factory=list)
    recommended_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis_id: str = ""
    source_fingerprint: str = ""
    candidates: list[VoiceCloneCandidate] = field(default_factory=list)
    recommended_candidate_id: str | None = None


@dataclass(slots=True)
class VoicePreviewRequest:
    profile_id: str
    text: str = ""
    speed: float = 1.0
    language: str = "auto"


@dataclass(slots=True)
class VoicePreviewResult:
    profile_id: str
    task_id: str = ""
    audio_path: str = ""
