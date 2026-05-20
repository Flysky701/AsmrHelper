"""Application resource service for workspace and model directories."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from src.core.runtime import ResourceStatus, RuntimeWorkspaceManager


class ResourceService:
    """Resolve and prepare app-level workspace resources."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        self._manager = RuntimeWorkspaceManager(self.project_root)

    def ensure_workspace(self) -> dict[str, Path]:
        workspace = self._manager.ensure_workspace()
        return {
            "project_root": Path(workspace.project_root),
            "output_dir": Path(workspace.output_dir),
            "models_dir": Path(workspace.models_dir),
        }

    def get_runtime_resources(self) -> dict[str, str]:
        workspace = self._manager.ensure_workspace()
        return {
            "project_root": workspace.project_root,
            "output_dir": workspace.output_dir,
            "models_dir": workspace.models_dir,
        }

    def check_required_resources(self) -> list[ResourceStatus]:
        return self._manager.check_required_resources()

    def get_runtime_capabilities(self) -> dict[str, object]:
        resources = self.get_runtime_resources()
        statuses = self.check_required_resources()
        return {
            "resources": resources,
            "checks": [
                {
                    "name": status.name,
                    "available": status.available,
                    "detail": status.detail,
                    "metadata": dict(status.metadata),
                }
                for status in statuses
            ],
        }

    def check_task_readiness(
        self,
        *,
        task_type: str,
        execution_profile: dict | None = None,
    ) -> dict[str, object]:
        statuses = self.check_required_resources()
        missing = [status.name for status in statuses if not status.available]
        return {
            "task_type": task_type,
            "ready": not missing,
            "missing_requirements": missing,
            "execution_profile": dict(execution_profile or {}),
        }


_service: ResourceService | None = None
_lock = threading.Lock()


def get_resource_service() -> ResourceService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ResourceService()
    return _service
