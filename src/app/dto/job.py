"""Job DTO for the task queue workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class Job:
    """Represents a single processing job in the workbench queue."""

    job_id: str
    job_type: str  # "pipeline"
    source_file: str  # input file path
    source_name: str  # display name (filename)
    status: str = "pending"  # pending / running / completed / failed / cancelled
    stage: str = ""  # current stage description
    progress: float = 0.0  # 0.0–1.0
    preset_id: str = ""
    resolved_options: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    primary_output: Optional[str] = None
    error: Optional[str] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    task_id: Optional[str] = None
