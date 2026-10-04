"""Core runtime workspace helpers."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, config
from src.workspace_paths import model_directory, resolve_directory

from .models import ResourceStatus, RuntimeWorkspace


class RuntimeWorkspaceManager:
    """Resolve and prepare runtime workspace directories."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or PROJECT_ROOT).resolve()

    def resolve_workspace(self) -> RuntimeWorkspace:
        return RuntimeWorkspace(
            project_root=str(self.project_root),
            output_dir=str(resolve_directory(config.get("paths.output_dir", ""), "output", project_root=self.project_root)),
            models_dir=str(model_directory(project_root=self.project_root)),
        )

    def ensure_workspace(self) -> RuntimeWorkspace:
        workspace = self.resolve_workspace()
        for value in (workspace.project_root, workspace.output_dir, workspace.models_dir):
            Path(value).mkdir(parents=True, exist_ok=True)
        return workspace

    def check_required_resources(self) -> list[ResourceStatus]:
        # Status reads must neither create missing directories nor report them ready.
        workspace = self.resolve_workspace()
        statuses = []
        for name, value in (("project_root", workspace.project_root),
                            ("output_dir", workspace.output_dir), ("models_dir", workspace.models_dir)):
            path = Path(value)
            try:
                available = path.is_dir()
                detail = "ready" if available else "not a directory" if path.exists() else "missing"
            except OSError:
                available, detail = False, "inaccessible"
            statuses.append(ResourceStatus(name=name, available=available, detail=detail, metadata={"path": value}))
        return statuses
