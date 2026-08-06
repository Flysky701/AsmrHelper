"""Schemas for task-driven pipeline run endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .tasks import TaskStatusResponse


class PipelineRunAcceptedResponse(BaseModel):
    task: TaskStatusResponse


class PipelineInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1)
    companion_paths: list[str] = Field(default_factory=list)


class PipelineOutputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = ""


class StageProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: str = Field(..., min_length=1)
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class PipelineStagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    separate: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="demucs",
            model="htdemucs",
        )
    )
    asr: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="faster_whisper",
            model="faster-whisper-base",
        )
    )
    translate: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="deepseek",
            model=None,
        )
    )
    tts: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="edge",
            model=None,
        )
    )
    mix: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="ffmpeg",
            model=None,
        )
    )
    export: StageProfileRequest = Field(
        default_factory=lambda: StageProfileRequest(
            provider="ffmpeg",
            model=None,
        )
    )


class PipelineExecutionProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    source_lang: Literal["ja", "zh", "en"] = "ja"
    target_lang: Literal["ja", "zh", "en"] = "zh"
    skip_existing: bool = False
    stages: PipelineStagesRequest = Field(default_factory=PipelineStagesRequest)


class PipelineRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: PipelineInputRequest
    output: PipelineOutputRequest = Field(default_factory=PipelineOutputRequest)
    execution_profile: PipelineExecutionProfileRequest = Field(
        default_factory=PipelineExecutionProfileRequest
    )
