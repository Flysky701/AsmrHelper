"""Application resource service for workspace and model directories."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from ..dto import ResourceStatus


class ResourceService:
    """Resolve and prepare app-level workspace resources."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()

    def ensure_workspace(self) -> dict[str, Path]:
        project_root = self.project_root
        output_dir = project_root / "output"
        models_dir = self._get_models_dir()

        project_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        models_dir.mkdir(parents=True, exist_ok=True)

        return {
            "project_root": project_root,
            "output_dir": output_dir,
            "models_dir": models_dir,
        }

    def check_required_resources(self) -> list[ResourceStatus]:
        workspace = self.ensure_workspace()
        return [
            ResourceStatus(
                name=name,
                available=path.exists(),
                detail="ready" if path.exists() else "missing",
                metadata={"path": str(path)},
            )
            for name, path in workspace.items()
        ]

    def _get_models_dir(self) -> Path:
        configured_root = os.getenv("ASMR_HELPER_MODEL_ROOT")
        if configured_root:
            return Path(configured_root).expanduser().resolve()
        return self.project_root / "models"


_service: ResourceService | None = None
_lock = threading.Lock()


def get_resource_service() -> ResourceService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ResourceService()
    return _service
