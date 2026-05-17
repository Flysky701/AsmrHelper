"""Pydantic schemas for pipeline endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    input_path: str = Field(..., description="Path to input audio file")
    output_dir: str = Field("", description="Output directory (default: project output/)")
    vtt_path: str | None = Field(None, description="Optional subtitle file path to translate")
    source_lang: str = Field("ja", description="Source language code (ja/zh/en)")
    target_lang: str = Field("zh", description="Target language code (ja/zh/en)")
    use_vocal_separator: bool = Field(True, description="Enable vocal separation before ASR")
    tts_engine: str = Field("edge", description="TTS engine (edge/qwen3)")
    tts_voice: str = Field("zh-CN-XiaoxiaoNeural", description="TTS voice name")
    vocal_model: str = Field("htdemucs", description="Vocal separation model")
    asr_model: str = Field("base", description="ASR model size")
    translate_provider: str = Field("deepseek", description="Translation provider (deepseek/openai)")
    tts_speed: float = Field(1.0, description="Speech speed for supported TTS engines")
    original_volume: float = Field(0.85, description="Original vocal volume used during mixing")
    tts_volume_ratio: float = Field(0.5, description="Relative synthesized voice volume")
    tts_delay: float = Field(0.0, description="TTS delay in seconds")
    skip_existing: bool = Field(False, description="Skip if output already exists")


class ArtifactSetResponse(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    primary_output: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    detail: str = ""


class PipelineRunResponse(BaseModel):
    success: bool
    input_path: str
    task_id: str | None = None
    task_state: str | None = None
    artifacts: ArtifactSetResponse = Field(default_factory=ArtifactSetResponse)
    mix_path: str | None = None
    exported_subtitle: str | None = None
    total_duration: float = 0.0
    error_message: str | None = None


class PipelinePresetsResponse(BaseModel):
    presets: list[str]
