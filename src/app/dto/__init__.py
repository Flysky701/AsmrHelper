"""Application-layer DTOs."""

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
    "SynthesisResult",
    "ResourceStatus",
    "ModelSummary",
    "ModelStatusView",
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
    source_lang: str = "ja"
    target_lang: str = "zh"
    tts_engine: str = "edge"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    vocal_model: str = "htdemucs"
    asr_model: str = "base"
    translate_provider: str = "deepseek"
    tts_delay: float = 0.0
    skip_existing: bool = False


@dataclass(slots=True)
class PipelineResult:
    success: bool
    input_path: str
    mix_path: Optional[str] = None
    exported_subtitle: Optional[str] = None
    steps: dict[str, Any] = field(default_factory=dict)
    total_duration: float = 0.0
    error_message: Optional[str] = None


@dataclass(slots=True)
class ArtifactSet:
    files: dict[str, str] = field(default_factory=dict)
    primary_output: Optional[str] = None


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
