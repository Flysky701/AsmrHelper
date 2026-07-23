"""Application-layer DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.core.artifacts import ArtifactRecord, ArtifactSet
from src.core.runtime import ResourceStatus
from src.core.sessions import InputAsset, ProcessingSession, WorkspaceContext
from src.core.subtitles import SubtitleAsset, SubtitleDocument, SubtitleSegment
from src.core.tasks import RuntimeEvent, TaskSpec, TaskStatus

from .audio_tools import (
    ConvertRequest,
    ConvertResult,
    SeparationRequest,
    SeparationResult,
    SplitRequest,
    SplitResult,
    SplitSegment,
    SubtitleTranslationRequest,
    SubtitleTranslationResult,
    VolumePreviewRequest,
    VolumePreviewResult,
)
from .batch_pipeline import BatchItemResult, BatchPipelineRequest, BatchPipelineResult
from .script_subtitle import ScriptSubtitleRequest, ScriptSubtitleResult
from .voice import (
    SegmentAnalyzeRequest,
    SegmentAnalyzeResult,
    SegmentInfo,
    VoiceCloneRequest,
    VoiceCloneResult,
    VoiceDesignRequest,
    VoiceDesignResult,
    VoiceProfileSummary,
    VoiceProfileView,
    VoicePreviewRequest,
    VoicePreviewResult,
)

__all__ = [
    "SubtitleSegment",
    "SubtitleDocument",
    "SubtitleAsset",
    "WorkspaceContext",
    "InputAsset",
    "ProcessingSession",
    "TaskSpec",
    "PipelineRequest",
    "PipelineResult",
    "ArtifactRecord",
    "ArtifactSet",
    "BatchPipelineRequest",
    "BatchItemResult",
    "BatchPipelineResult",
    "ConvertRequest",
    "ConvertResult",
    "SeparationRequest",
    "SeparationResult",
    "SplitRequest",
    "SplitResult",
    "SplitSegment",
    "SubtitleTranslationRequest",
    "SubtitleTranslationResult",
    "ScriptSubtitleRequest",
    "ScriptSubtitleResult",
    "VolumePreviewRequest",
    "VolumePreviewResult",
    "SegmentAnalyzeRequest",
    "SegmentAnalyzeResult",
    "SegmentInfo",
    "VoiceCloneRequest",
    "VoiceCloneResult",
    "VoiceDesignRequest",
    "VoiceDesignResult",
    "VoiceProfileSummary",
    "VoiceProfileView",
    "VoicePreviewRequest",
    "VoicePreviewResult",
    "TaskStatus",
    "RuntimeEvent",
    "TranslationResult",
    "TranscriptionResult",
    "SynthesisResult",
    "ResourceStatus",
    "ModelSummary",
    "ModelStatusView",
    "ModelStatusIssueView",
    "ModelOperationResult",
    "ModelVerificationResult",
]


@dataclass(slots=True)
class PipelineRequest:
    input_path: str
    output_dir: str = ""
    vtt_path: Optional[str] = None
    source_lang: str = "ja"
    target_lang: str = "zh"
    use_vocal_separator: bool = True
    tts_engine: str = "edge"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    vocal_model: str = "htdemucs"
    asr_model: str = "faster-whisper-base"
    translate_provider: str = "deepseek"
    translate_model: str = ""
    tts_speed: float = 1.0
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5
    tts_delay: float = 0.0
    skip_existing: bool = False
    voice_profile_id: Optional[str] = None
    output_mode: str = "single"
    batch_root_dir: str = ""
    engine_params: dict = field(default_factory=dict)
    companion_paths: list[str] = field(default_factory=list)
    execution_profile: dict = field(default_factory=dict)


@dataclass(slots=True)
class PipelineResult:
    success: bool
    input_path: str
    task: Optional["TaskStatus"] = None
    task_id: Optional[str] = None
    task_state: Optional[str] = None
    artifacts: ArtifactSet = field(default_factory=lambda: ArtifactSet())
    mix_path: Optional[str] = None
    exported_subtitle: Optional[str] = None
    steps: dict[str, Any] = field(default_factory=dict)
    total_duration: float = 0.0
    error_message: Optional[str] = None


@dataclass(slots=True)
class TranslationResult:
    items: list[str] = field(default_factory=list)
    provider: str = ""
    source_lang: str = ""
    target_lang: str = ""


@dataclass(slots=True)
class TranscriptionResult:
    segments: list[SubtitleSegment] = field(default_factory=list)
    output_path: Optional[str] = None
    text: str = ""


@dataclass(slots=True)
class SynthesisResult:
    engine: str
    voice: str
    output_path: str


@dataclass(slots=True)
class ModelSummary:
    model_id: str
    kind: str
    category: str
    backend: str
    display_name: str
    supports_install: bool = False
    supports_remove: bool = False
    family_id: str | None = None
    variant_group: str | None = None
    variant_tier: str | None = None
    is_primary_variant: bool = False
    dependency_group: str | None = None
    runtime_profile: str | None = None
    preferred_runtime: str | None = None
    install_modes: list[str] = field(default_factory=list)
    default_install_mode: str | None = None
    required_assets: list[str] = field(default_factory=list)
    recommended_assets: list[str] = field(default_factory=list)
    required_system_tools: list[str] = field(default_factory=list)
    supported_os: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelStatusIssueView:
    code: str
    requirement: str
    message: str


@dataclass(slots=True)
class ModelStatusView:
    model_id: str
    status: str
    detail: str
    executable: bool = False
    issues: list[ModelStatusIssueView] = field(default_factory=list)


@dataclass(slots=True)
class ModelOperationResult:
    action: str
    model_id: str
    success: bool
    status: str
    detail: str


@dataclass(slots=True)
class ModelVerificationResult:
    model_id: str
    success: bool
    status: str
    detail: str
