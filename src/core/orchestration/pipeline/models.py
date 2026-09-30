"""Core pipeline orchestration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PipelineMode(str, Enum):
    FULL = "full"
    ASR_ONLY = "asr_only"
    SUBTITLE_ONLY = "subtitle_only"
    TTS_ONLY = "tts_only"
    CUSTOM = "custom"


class StageKind(str, Enum):
    SEPARATION = "separation"
    ASR = "asr"
    ALIGN = "align"
    TRANSLATION = "translation"
    TTS = "tts"
    MIX = "mix"


@dataclass(slots=True)
class StageBinding:
    """A single stage's engine binding and options."""
    kind: StageKind
    provider: str
    model: str = "default"
    enabled: bool = True
    common_options: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MixConfig:
    """Mix stage configuration."""
    enabled: bool = True
    original_volume: float = 0.85
    tts_volume_ratio: float = 0.5
    tts_delay_ms: float = 0.0


@dataclass(slots=True)
class SubtitleConfig:
    """Subtitle handling configuration."""
    enabled: bool = True
    clean_enabled: bool = True
    clean_sound_effects: bool = True
    clean_speaker_names: bool = True
    export_format: str = "srt"


@dataclass(slots=True)
class PipelineExecutionPlan:
    """Structured execution plan for a pipeline run.

    This domain object captures execution intent for the pipeline executor.
    """
    # Identity
    task_id: str

    # I/O
    input_path: str
    output_dir: str
    companion_subtitle_path: str | None = None
    companion_subtitle_paths: list[str] = field(default_factory=list)
    workflow: dict[str, Any] = field(default_factory=dict)

    # Language
    source_lang: str = "ja"
    target_lang: str = "zh"
    source_label: str = "日文"
    target_label: str = "中文"

    # Pipeline behavior
    mode: PipelineMode = PipelineMode.FULL
    skip_existing: bool = False
    output_mode: str = "single"
    batch_root_dir: str = ""

    # Stage bindings
    separation: StageBinding = field(default_factory=lambda: StageBinding(
        kind=StageKind.SEPARATION, provider="demucs", model="htdemucs",
    ))
    asr: StageBinding = field(default_factory=lambda: StageBinding(
        kind=StageKind.ASR, provider="faster_whisper", model="faster-whisper-base",
    ))
    translation: StageBinding = field(default_factory=lambda: StageBinding(
        kind=StageKind.TRANSLATION, provider="deepseek", model="default",
    ))
    alignment: StageBinding = field(default_factory=lambda: StageBinding(
        kind=StageKind.ALIGN, provider="qwen3_forced_aligner", model="qwen3-forced-aligner-0.6b", enabled=False,
    ))
    tts: StageBinding = field(default_factory=lambda: StageBinding(
        kind=StageKind.TTS, provider="edge", model="default",
    ))

    # Mix and subtitle
    mix: MixConfig = field(default_factory=MixConfig)
    subtitle: SubtitleConfig = field(default_factory=SubtitleConfig)

    @property
    def active_stage_kinds(self) -> list[StageKind]:
        """Return the stage kinds that are enabled in this plan."""
        stages = []
        if self.separation.enabled:
            stages.append(StageKind.SEPARATION)
        if self.asr.enabled:
            stages.append(StageKind.ASR)
        if self.alignment.enabled:
            stages.append(StageKind.ALIGN)
        if self.translation.enabled or self.translation.common_options.get("reuse_only"):
            stages.append(StageKind.TRANSLATION)
        if self.tts.enabled:
            stages.append(StageKind.TTS)
        if self.mix.enabled:
            stages.append(StageKind.MIX)
        return stages

@dataclass(slots=True)
class PipelineExecutionContext:
    """Input context for building a PipelineExecutionPlan."""
    task_id: str
    input_path: str
    output_dir: str
    source_lang: str = "ja"
    target_lang: str = "zh"
    companion_subtitle_path: str | None = None
    companion_subtitle_paths: list[str] = field(default_factory=list)
    execution_profile: dict[str, Any] = field(default_factory=dict)
