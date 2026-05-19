"""Pydantic schemas for job endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobCreateItem(BaseModel):
    source_file: str = Field(..., description="Path to input audio file")
    source_name: str = Field("", description="Display name (defaults to filename)")


class JobCreateRequest(BaseModel):
    items: list[JobCreateItem] = Field(..., min_length=1, description="Files to create jobs for")
    preset_id: str = Field("", description="Pipeline preset ID")
    resolved_options: dict = Field(default_factory=dict, description="Full parameter snapshot")


class JobResponse(BaseModel):
    job_id: str
    job_type: str
    source_file: str
    source_name: str
    status: str
    stage: str
    progress: float
    preset_id: str
    resolved_options: dict
    artifacts: dict[str, str]
    primary_output: str | None
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None
    task_id: str | None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int


class JobActionRequest(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, description="Job IDs to act on")


class JobDiscoverRequest(BaseModel):
    directory: str = Field(..., description="Directory to scan for audio files")
    extensions: list[str] = Field(
        default=[".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"],
        description="File extensions to include",
    )
