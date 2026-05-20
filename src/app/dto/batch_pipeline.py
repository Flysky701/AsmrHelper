"""DTOs for batch pipeline application workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class BatchPipelineRequest:
    """Stable request payload for batch pipeline service calls."""

    input_files: list[str] = field(default_factory=list)
    input_dir: str = ""
    output_base_dir: str = ""
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
    skip_existing: bool = True
    max_workers: int = 1
    use_batch_output_structure: bool = False
    voice_profile_id: Optional[str] = None


@dataclass(slots=True)
class BatchItemResult:
    """Result for a single file inside a batch request."""

    file: str
    status: str
    task_id: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0


@dataclass(slots=True)
class BatchPipelineResult:
    """Aggregate result for a batch pipeline request."""

    items: list[BatchItemResult] = field(default_factory=list)
    total_count: int = 0
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_duration: float = 0.0
