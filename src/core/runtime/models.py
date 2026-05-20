"""Core runtime models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ResourceStatus:
    name: str
    available: bool
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeWorkspace:
    project_root: str
    output_dir: str
    models_dir: str
