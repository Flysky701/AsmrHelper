"""Core pipeline orchestration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PipelineExecutionContext:
    task_id: str
    input_path: str
    output_dir: str
    source_lang: str = "ja"
    target_lang: str = "zh"
    companion_subtitle_path: str | None = None
    execution_profile: dict[str, Any] = field(default_factory=dict)
