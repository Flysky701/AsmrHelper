"""Pydantic schemas for pipeline endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .tasks import TaskStatusResponse


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
    asr_model: str = Field("faster-whisper-base", description="ASR model id")
    translate_provider: str = Field("deepseek", description="Translation provider (deepseek/openai)")
    tts_speed: float = Field(1.0, description="Speech speed for supported TTS engines")
    original_volume: float = Field(0.85, description="Original vocal volume used during mixing")
    tts_volume_ratio: float = Field(0.5, description="Relative synthesized voice volume")
    tts_delay: float = Field(0.0, description="TTS delay in seconds")
    skip_existing: bool = Field(False, description="Skip if output already exists")
    voice_profile_id: str | None = Field(None, description="Voice profile ID for Qwen3-TTS")
    engine_params: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-engine parameters keyed by engine ID, e.g. {qwen3: {emotion: 'happy'}}",
    )


class ArtifactSetResponse(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    primary_output: str | None = None


class PipelineRunResponse(BaseModel):
    success: bool
    input_path: str
    task: TaskStatusResponse | None = None
    task_id: str | None = None
    task_state: str | None = None
    artifacts: ArtifactSetResponse = Field(default_factory=ArtifactSetResponse)
    mix_path: str | None = None
    exported_subtitle: str | None = None
    total_duration: float = 0.0
    error_message: str | None = None


class PresetItem(BaseModel):
    id: str
    label: str
    description: str
    stages: list[str] = Field(default_factory=list)


class PipelinePresetsResponse(BaseModel):
    presets: list[PresetItem]


class BatchPipelineRequest(BaseModel):
    input_files: list[str] = Field(default_factory=list, description="List of input file paths")
    input_dir: str = Field("", description="Input directory (alternative to input_files)")
    output_base_dir: str = Field("", description="Base output directory")
    source_lang: str = Field("ja", description="Source language code")
    target_lang: str = Field("zh", description="Target language code")
    use_vocal_separator: bool = Field(True, description="Enable vocal separation")
    tts_engine: str = Field("edge", description="TTS engine")
    tts_voice: str = Field("zh-CN-XiaoxiaoNeural", description="TTS voice name")
    vocal_model: str = Field("htdemucs", description="Vocal separation model")
    asr_model: str = Field("faster-whisper-base", description="ASR model id")
    translate_provider: str = Field("deepseek", description="Translation provider")
    tts_speed: float = Field(1.0, description="Speech speed")
    original_volume: float = Field(0.85, description="Original vocal volume")
    tts_volume_ratio: float = Field(0.5, description="TTS volume ratio")
    tts_delay: float = Field(0.0, description="TTS delay in seconds")
    skip_existing: bool = Field(True, description="Skip if output already exists")
    max_workers: int = Field(1, description="Max parallel workers")
    use_batch_output_structure: bool = Field(False, description="Use batch output directory structure")
    voice_profile_id: str | None = Field(None, description="Voice profile ID for Qwen3-TTS")


class BatchItemResultResponse(BaseModel):
    file: str
    status: str
    task_id: str | None = None
    output: str | None = None
    error: str | None = None
    duration: float = 0.0


class BatchPipelineResponse(BaseModel):
    items: list[BatchItemResultResponse] = Field(default_factory=list)
    total_count: int = 0
    success_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_duration: float = 0.0
