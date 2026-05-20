"""Application-layer DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

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
    "TranslationResult",
    "TranscriptionResult",
    "SynthesisResult",
    "ResourceStatus",
    "ModelSummary",
    "ModelStatusView",
    "ModelOperationResult",
    "ModelVerificationResult",
]


@dataclass(slots=True)
class SubtitleSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class SubtitleDocument:
    segments: list[SubtitleSegment] = field(default_factory=list)


@dataclass(slots=True)
class SubtitleAsset:
    asset_id: str
    format: str
    document: SubtitleDocument = field(default_factory=SubtitleDocument)
    source_path: str = ""
    line_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkspaceContext:
    workspace_id: str
    workspace_root: str
    default_output_root: str
    default_temp_root: str
    default_models_root: str


@dataclass(slots=True)
class InputAsset:
    asset_id: str
    absolute_path: str
    kind: str
    display_name: str = ""
    extension: str = ""
    exists: bool = False
    readable: bool = False
    size_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    related_assets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessingSession:
    session_id: str
    workspace_id: str
    mode: str
    input_asset_ids: list[str] = field(default_factory=list)
    primary_input_asset_id: str = ""
    companion_asset_ids: list[str] = field(default_factory=list)
    resolved_output_dir: str = ""
    resolved_temp_dir: str = ""
    status: str = "ready"
    validation: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskSpec:
    task_id: str
    task_type: str
    task_source: str
    session_id: str
    input_asset_id: str = ""
    companion_asset_ids: list[str] = field(default_factory=list)
    execution_profile: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    dedupe_key: str = ""
    created_at: str = ""


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
    asr_model: str = "base"
    translate_provider: str = "deepseek"
    tts_speed: float = 1.0
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5
    tts_delay: float = 0.0
    skip_existing: bool = False
    voice_profile_id: Optional[str] = None
    output_mode: str = "single"
    batch_root_dir: str = ""


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
class ArtifactSet:
    files: dict[str, str] = field(default_factory=dict)
    primary_output: Optional[str] = None
    entries: list["ArtifactRecord"] = field(default_factory=list)

    @classmethod
    def from_optional_paths(
        cls,
        *,
        primary_output: Optional[str] = None,
        **files: Optional[str],
    ) -> "ArtifactSet":
        return cls(
            files={name: path for name, path in files.items() if path},
            primary_output=primary_output,
        )

    def get(self, name: str) -> Optional[str]:
        return self.files.get(name)


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    task_id: str
    artifact_type: str
    path: str
    label: str = ""
    preview_kind: str = ""
    stage: str = ""
    is_primary: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskStatus:
    task_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    detail: str = ""
    task_type: str = ""
    task_source: str = ""
    session_id: str = ""


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
class ResourceStatus:
    name: str
    available: bool
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelSummary:
    model_id: str
    kind: str
    category: str
    backend: str
    display_name: str


@dataclass(slots=True)
class ModelStatusView:
    model_id: str
    status: str
    detail: str


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
