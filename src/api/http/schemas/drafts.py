"""Pydantic schemas for `/api/v1/drafts` endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    force_asr: bool = False
    asr_provider: str | None = None
    asr_model: str | None = None
    asr_options: dict[str, Any] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_options: dict[str, Any] | None = None
    voice_plan: dict[str, Any] | None = None
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
    enable_dubbing: bool = True
    bilingual: bool = True
    mix_options: dict[str, Any] | None = None
    expected_revision: int | None = None


class QualityAuditReportResponse(BaseModel):
    draft_id: str | None = None
    state: str | None = None
    revision: int | None = None
    untranslated_indices: list[int] = Field(default_factory=list)
    japanese_residue_indices: list[int] = Field(default_factory=list)
    empty_or_symbol_indices: list[int] = Field(default_factory=list)
    over_speed_cues: list[dict[str, Any]] = Field(default_factory=list)
    summary_counts: dict[str, int] = Field(default_factory=dict)
    gate_passed: bool = False
    chars_per_second: float = 4.2
    max_atempo: float = 1.35
    reference_quality: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class DraftSessionResponse(BaseModel):
    draft_id: str
    state: str
    work_dir: str
    title: str
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    voice_plan: dict[str, Any] = Field(default_factory=dict)
    audit_report: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    revision: int
    created_at: str
    updated_at: str


class DraftListResponse(BaseModel):
    drafts: list[DraftSessionResponse] = Field(default_factory=list)
