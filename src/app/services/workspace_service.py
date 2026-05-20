"""Workspace resolution service."""

from __future__ import annotations

import threading
from src.core.sessions import WorkspaceContext, WorkspaceResolver


class WorkspaceService:
    """Resolve workspace defaults for the current installation."""

    def __init__(self, resolver: WorkspaceResolver | None = None) -> None:
        self._resolver = resolver or WorkspaceResolver()

    def resolve(self) -> WorkspaceContext:
        return self._resolver.resolve()


_service: WorkspaceService | None = None
_lock = threading.Lock()


def get_workspace_service() -> WorkspaceService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = WorkspaceService()
    return _service
