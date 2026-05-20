"""Workspace resolution primitives."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, config

from .models import WorkspaceContext


class WorkspaceResolver:
    """Resolve workspace directories from project config."""

    def resolve(self) -> WorkspaceContext:
        settings = config.to_dict()
        paths = settings.get("paths", {})

        workspace_root = PROJECT_ROOT.resolve()
        output_root = Path(paths.get("output_dir") or workspace_root / "output").resolve()
        temp_root = Path(paths.get("temp_dir") or workspace_root / "debug" / "runtime").resolve()
        models_root = Path(paths.get("model_cache_dir") or workspace_root / "models").resolve()

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
