"""Core artifact domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    task_id: str
    artifact_type: str
    path: str
    label: str = ""
    preview_kind: str = ""
    stage: str = ""
    is_primary: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArtifactSet:
    files: dict[str, str] = field(default_factory=dict)
    primary_output: Optional[str] = None
    entries: list[ArtifactRecord] = field(default_factory=list)

    @classmethod
    def from_optional_paths(
        cls,
        *,
        primary_output: Optional[str] = None,
        **files: Optional[str],
    ) -> "ArtifactSet":
        return cls(
            files={name: path for name, path in files.items() if path},
            primary_output=primary_output,
        )

    def get(self, name: str) -> Optional[str]:
        return self.files.get(name)
