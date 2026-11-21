"""Pydantic schemas for `/api/v1/drafts` endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from packages.protocol.drafts import DraftSession, QualityAuditReport


class DraftSessionResponse(DraftSession):
    """Public REST model for a persisted draft."""


class QualityAuditReportResponse(QualityAuditReport):
    """Public REST model for a draft audit."""


class InspectWorkRequest(BaseModel):
    path_or_dir: str


class InspectWorkResponse(BaseModel):
    work_dir: str
    title: str
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    audio_files: list[dict[str, Any]] = Field(default_factory=list)
    subtitles: list[dict[str, Any]] = Field(default_factory=list)
    scripts: list[dict[str, Any]] = Field(default_factory=list)
    stem_pairs: list[dict[str, Any]] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)


class PrepareDraftRequest(BaseModel):
    path_or_dir: str
    track_path: str | None = None
    subtitle_path: str | None = None
    script_path: str | None = None
    title: str | None = None
    source_lang: str = "ja"
    target_lang: str = "zh"
    enable_translation: bool = True
    duration_aware: bool = False
    auto_detect_delivery: bool = False
    force_asr: bool = False
    asr_provider: str | None = None
    asr_model: str | None = None
    asr_options: dict[str, Any] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_options: dict[str, Any] | None = None
    voice_plan: dict[str, Any] | None = None
    prepare_stems: bool = False
    separation_model: str | None = None
    extract_voice_reference: bool = False
    synthesize_samples: bool = False
    sample_cue_count: int = Field(default=0, ge=0, le=2)
    chars_per_second: float = Field(default=4.2, gt=0.0)
    max_atempo: float = Field(default=1.35, ge=1.0)


class DraftSegmentEditRequest(BaseModel):
    index: int | None = None
    cue_id: str | None = None
    source_text: str | None = None
    translation: str | None = None
    start: float | None = None
    end: float | None = None
    speaker: str | None = None
    delivery: str | None = None
    emotion: str | None = None


class PatchDraftRequest(BaseModel):
    edits: list[DraftSegmentEditRequest] = Field(default_factory=list)
    voice_plan_patch: dict[str, Any] | None = None
    title: str | None = None
    expected_revision: int | None = None


class CommitDraftRequest(BaseModel):
    output_dir: str
    export_formats: list[str] = Field(default_factory=lambda: ["srt", "lrc"])
    regenerate_cue_ids: list[str] = Field(default_factory=list, description="Force new takes only for these cue IDs; all other cues must have cached audio.")
    enable_dubbing: bool = True
    bilingual: bool = True
    mix_options: dict[str, Any] | None = None
    expected_revision: int | None = None


class DraftListResponse(BaseModel):
    drafts: list[DraftSessionResponse] = Field(default_factory=list)
