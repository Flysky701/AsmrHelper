"""Persistent draft and audit data shared by REST and Agent clients."""
from typing import Any

from pydantic import BaseModel, Field


class QualityAuditReport(BaseModel):
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
    script_alignment: dict[str, Any] | None = None
    reference_quality: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class DraftSession(BaseModel):
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
