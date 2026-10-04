"""Workspace resolution primitives."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, config
from src.workspace_paths import model_directory, resolve_directory

from .models import WorkspaceContext


class WorkspaceResolver:
    """Resolve workspace directories from project config."""

    def resolve(self) -> WorkspaceContext:
        settings = config.to_dict()
        paths = settings.get("paths", {})

        workspace_root = PROJECT_ROOT.resolve()
        output_root = resolve_directory(paths.get("output_dir"), "output", project_root=workspace_root)
        temp_root = resolve_directory(paths.get("temp_dir"), "debug/runtime", project_root=workspace_root)
        models_root = model_directory(project_root=workspace_root)

        output_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        models_root.mkdir(parents=True, exist_ok=True)

        return WorkspaceContext(
            workspace_id="default-workspace",
            workspace_root=str(workspace_root),
            default_output_root=str(output_root),
            default_temp_root=str(temp_root),
            default_models_root=str(models_root),
        )
