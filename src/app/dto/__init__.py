"""Application-layer DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "SubtitleSegment",
    "SubtitleDocument",
    "PipelineRequest",
    "PipelineResult",
    "ArtifactSet",
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
class TaskStatus:
    task_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    detail: str = ""


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
