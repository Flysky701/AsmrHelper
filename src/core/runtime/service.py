"""Core runtime workspace helpers."""

from __future__ import annotations

import os
from pathlib import Path

from .models import ResourceStatus, RuntimeWorkspace


class RuntimeWorkspaceManager:
    """Resolve and prepare runtime workspace directories."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()

    def ensure_workspace(self) -> RuntimeWorkspace:
        project_root = self.project_root
        output_dir = project_root / "output"
        models_dir = self._get_models_dir()

        project_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        models_dir.mkdir(parents=True, exist_ok=True)

        return RuntimeWorkspace(
            project_root=str(project_root),
            output_dir=str(output_dir),
            models_dir=str(models_dir),
        )

    def check_required_resources(self) -> list[ResourceStatus]:
        workspace = self.ensure_workspace()
        return [
            ResourceStatus(
                name=name,
                available=Path(path).exists(),
                detail="ready" if Path(path).exists() else "missing",
                metadata={"path": path},
            )
            for name, path in (
                ("project_root", workspace.project_root),
                ("output_dir", workspace.output_dir),
                ("models_dir", workspace.models_dir),
            )
        ]

    def _get_models_dir(self) -> Path:
        configured_root = os.getenv("ASMR_HELPER_MODEL_ROOT")
        if configured_root:
            return Path(configured_root).expanduser().resolve()
        return self.project_root / "models"
