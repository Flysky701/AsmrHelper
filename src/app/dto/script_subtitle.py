"""DTOs for script-to-subtitle application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class ScriptSubtitleRequest:
    """Stable request payload for script-to-subtitle service calls."""

    script_path: str
    output_path: str = ""
    audio_path: Optional[str] = None
    vtt_path: Optional[str] = None
    fmt: str = "vtt"
    use_llm_clean: bool = True
    asr_model_size: str = "large-v3"
    asr_language: str = "ja"
    track_index: Optional[int] = None
    vertical_mode: str = "auto"
    debug_dir: Optional[str] = None


@dataclass(slots=True)
class ScriptSubtitleResult:
    """Application-facing result for script-to-subtitle service calls."""

    mode: str
    output_path: Optional[str] = None
    text: str = ""
    line_count: int = 0
