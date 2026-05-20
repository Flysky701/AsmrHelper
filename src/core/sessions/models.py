"""Core session and input domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkspaceContext:
    workspace_id: str
    workspace_root: str
    default_output_root: str
    default_temp_root: str
    default_models_root: str


@dataclass(slots=True)
class InputAsset:
    asset_id: str
    absolute_path: str
    kind: str
    display_name: str = ""
    extension: str = ""
    exists: bool = False
    readable: bool = False
    size_bytes: int = 0
    warnings: list[str] = field(default_factory=list)
    related_assets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessingSession:
    session_id: str
    workspace_id: str
    mode: str
    input_asset_ids: list[str] = field(default_factory=list)
    primary_input_asset_id: str = ""
    companion_asset_ids: list[str] = field(default_factory=list)
    resolved_output_dir: str = ""
    resolved_temp_dir: str = ""
    status: str = "ready"
    validation: dict[str, Any] = field(default_factory=dict)
