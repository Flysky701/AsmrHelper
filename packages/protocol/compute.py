"""Pure Pydantic v2 data contracts for stateless GPU compute RPC.

This module defines request/response models shared between `packages/core`,
local `.runtimes` subprocess workers, and remote Colab / HTTP GPU workers.
It MUST NOT import PyTorch, FastAPI, SQLite, FFmpeg, or application state.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ComputeErrorPayload

PROTOCOL_VERSION = "1.0"
AudioFormat = Literal["flac", "wav"]
DEFAULT_SUPPORTED_TASKS: tuple[str, ...] = ("separate", "asr", "align", "tts_batch")


class WorkerCapabilities(BaseModel):
    """Runtime hardware and resident-model capabilities reported by a GPU worker."""

    model_config = ConfigDict(extra="ignore")

    device: str = Field(default="cpu", min_length=1)
    device_name: str | None = None
    cuda_available: bool = False
    vram_total_mb: int = Field(default=0, ge=0)
    vram_free_mb: int | None = Field(default=None, ge=0)
    loaded_models: list[str] = Field(default_factory=list)
    supported_tasks: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SUPPORTED_TASKS)
    )
    protocol_version: str = Field(default=PROTOCOL_VERSION, min_length=1)


class LeaseEvictRequest(BaseModel):
    """Request to evict one model family/key or all idle models from worker VRAM."""

    model_config = ConfigDict(extra="ignore")

    family: str | None = None
    key: str | None = None


class LeaseEvictResult(BaseModel):
    """Result of a VRAM lease eviction operation."""

    model_config = ConfigDict(extra="ignore")

    evicted: list[str] = Field(default_factory=list)
    loaded_models: list[str] = Field(default_factory=list)


class SeparationRequest(BaseModel):
    """Stateless vocal/stem separation request."""

    model_config = ConfigDict(extra="ignore")

    input_path: str | None = None
    output_dir: str | None = None
    model: str = Field(default="htdemucs", min_length=1)
    stems: list[str] = Field(default_factory=lambda: ["vocals"])
    output_format: AudioFormat = "flac"
    audio_b64: str | None = None
    audio_filename: str | None = None

    @model_validator(mode="after")
    def _validate_stems(self) -> SeparationRequest:
        cleaned = [s.strip() for s in self.stems if s and s.strip()]
        if not cleaned:
            raise ValueError("stems must contain at least one stem name")
        self.stems = cleaned
        return self


class SeparationResult(BaseModel):
    """Stateless vocal/stem separation result."""

    model_config = ConfigDict(extra="ignore")

    model: str = "htdemucs"
    stem_paths: dict[str, str] = Field(default_factory=dict)
    stem_audio_b64: dict[str, str] = Field(default_factory=dict)
    output_format: AudioFormat = "flac"
    sample_rate: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    warnings: list[str] = Field(default_factory=list)


class AsrRequest(BaseModel):
    """Stateless ASR transcription request."""

    model_config = ConfigDict(extra="ignore")

    input_path: str | None = None
    output_path: str | None = None
    provider: str = Field(default="faster_whisper", min_length=1)
    model: str = "large-v3"
    language: str = Field(default="ja", min_length=1)
    timestamps: bool = True
    vad_filter: bool = True
    common_options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] | None = None
    audio_b64: str | None = None
    audio_filename: str | None = None

    @model_validator(mode="after")
    def _sync_profile(self) -> AsrRequest:
        if self.profile is not None:
            prof = dict(self.profile)
            common = dict(prof.get("common_options") or {})
            prov_opts = dict(prof.get("provider_options") or {})
            if prof.get("provider"):
                self.provider = str(prof["provider"])
            if "model" in prof and prof["model"] is not None:
                self.model = str(prof["model"])
            if common.get("language"):
                self.language = str(common["language"])
            if "timestamps" in common:
                self.timestamps = bool(common["timestamps"])
            if "vad_filter" in prov_opts:
                self.vad_filter = bool(prov_opts["vad_filter"])
            merged_common = {**common, **self.common_options}
            merged_prov = {**prov_opts, **self.provider_options}
            self.common_options = merged_common
            self.provider_options = merged_prov
        return self

    def to_profile(self) -> dict[str, Any]:
        """Build an `AsrEngineRuntime`-compatible profile dictionary."""
        common = {
            "language": self.language,
            "timestamps": self.timestamps,
            **self.common_options,
        }
        provider_opts = dict(self.provider_options)
        if self.provider == "faster_whisper" and "vad_filter" not in provider_opts:
            provider_opts["vad_filter"] = self.vad_filter
        return {
            "provider": self.provider,
            "model": self.model,
            "common_options": common,
            "provider_options": provider_opts,
        }


class AsrSegmentItem(BaseModel):
    """Single recognized speech cue with timestamps in seconds."""

    model_config = ConfigDict(extra="ignore")

    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    text: str = ""
    language: str = ""
    confidence: float | None = None
    recognition_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_span(self) -> AsrSegmentItem:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self


class AsrResult(BaseModel):
    """Stateless ASR transcription result."""

    model_config = ConfigDict(extra="ignore")

    segments: list[AsrSegmentItem] = Field(default_factory=list)
    language: str = "ja"
    provider: str = ""
    model: str = ""
    duration_seconds: float | None = Field(default=None, ge=0.0)
    source_path: str = ""
    format: str = ""
    warnings: list[str] = Field(default_factory=list)

    def to_worker_document(self) -> dict[str, Any]:
        """Convert to legacy `RuntimeRouter` / `stage_worker` document envelope."""
        return {
            "document": {
                "segments": [
                    {
                        "start": seg.start,
                        "end": seg.end,
                        "text": seg.text,
                        "language": seg.language or self.language,
                        "confidence": seg.confidence,
                        "recognition_metadata": dict(seg.recognition_metadata),
                    }
                    for seg in self.segments
                ],
                "language": self.language,
                "format": self.format,
                "source_path": self.source_path,
                "warnings": list(self.warnings),
            }
        }


class AlignmentWordItem(BaseModel):
    """Word- or token-level forced alignment timestamp item."""

    model_config = ConfigDict(extra="ignore")

    text: str
    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    segment_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_span(self) -> AlignmentWordItem:
        if self.end < self.start:
            raise ValueError(f"word end ({self.end}) must be >= start ({self.start})")
        return self


class AlignmentRequest(BaseModel):
    """Stateless forced alignment request."""

    model_config = ConfigDict(extra="ignore")

    input_path: str | None = None
    segments: list[dict[str, Any]] = Field(..., min_length=1)
    language: str = Field(default="ja", min_length=1)
    model: str = Field(default="qwen3-forced-aligner-0.6b", min_length=1)
    audio_b64: str | None = None
    audio_filename: str | None = None

    @model_validator(mode="after")
    def _validate_non_empty_text(self) -> AlignmentRequest:
        if not any(str(seg.get("text", "")).strip() for seg in self.segments):
            raise ValueError("segments must contain at least one non-empty text entry")
        return self


class AlignmentResult(BaseModel):
    """Stateless forced alignment result (timestamps in seconds)."""

    model_config = ConfigDict(extra="ignore")

    segments: list[dict[str, Any]] = Field(default_factory=list)
    words: list[AlignmentWordItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = "qwen3-forced-aligner-0.6b"
    time_unit: str = "seconds"

    def to_runtime_dict(self) -> dict[str, Any]:
        """Convert to `AlignmentRuntime.align_file` compatible dictionary."""
        return {
            "segments": [dict(seg) for seg in self.segments],
            "words": [w.model_dump() for w in self.words],
            "warnings": list(self.warnings),
            "model": self.model,
            "time_unit": self.time_unit,
        }


class TtsSynthesizeItem(BaseModel):
    """Single cue synthesis item within a batch TTS request."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    output_path: str | None = None
    language: str = "zh"
    speaker: str | None = None
    instruction: str = ""
    variant_kind: Literal["default", "preset", "design", "reference"] = "default"
    variant_value: str = ""
    reference_id: str | None = None
    reference_transcript: str = ""
    options: dict[str, Any] = Field(default_factory=dict)


class TtsBatchRequest(BaseModel):
    """Stateless batch local TTS synthesis request."""

    model_config = ConfigDict(extra="ignore")

    provider_id: str = Field(default="qwen3", min_length=1)
    model: str = ""
    device: str = "auto"
    precision: str = "auto"
    output_format: AudioFormat = "flac"
    items: list[TtsSynthesizeItem] = Field(..., min_length=1)
    reference_audio_path: str | None = None
    reference_audio_b64: str | None = None
    reference_audio_filename: str | None = None
    references: dict[str, str] = Field(default_factory=dict)
    references_b64: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class TtsBatchItemResult(BaseModel):
    """Synthesis result for a single `TtsSynthesizeItem`."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(..., min_length=1)
    ok: bool = True
    output_path: str | None = None
    audio_b64: str | None = None
    output_format: AudioFormat = "flac"
    sample_rate: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    error: ComputeErrorPayload | None = None


class TtsBatchResult(BaseModel):
    """Stateless batch TTS synthesis result."""

    model_config = ConfigDict(extra="ignore")

    provider_id: str
    model: str = ""
    output_format: AudioFormat = "flac"
    items: list[TtsBatchItemResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
