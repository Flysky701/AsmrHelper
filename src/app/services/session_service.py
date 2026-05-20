"""Processing session service."""

from __future__ import annotations

import threading
from src.core.sessions import ProcessingSession, SessionRegistry
from ..errors import AppValidationError
from .input_catalog_service import InputCatalogService, get_input_catalog_service
from .workspace_service import WorkspaceService, get_workspace_service


class SessionService:
    """Create and resolve processing sessions."""

    def __init__(
        self,
        workspace_service: WorkspaceService | None = None,
        input_catalog_service: InputCatalogService | None = None,
    ) -> None:
        self.workspace_service = workspace_service or get_workspace_service()
        self.input_catalog_service = input_catalog_service or get_input_catalog_service()
        self._lock = threading.Lock()
        self._registry: SessionRegistry | None = None

    def _get_registry(self) -> SessionRegistry:
        if self._registry is None:
            workspace = self.workspace_service.resolve()
            catalog = self.input_catalog_service._catalog
            self._registry = SessionRegistry(workspace=workspace, input_catalog=catalog)
        return self._registry

    def create_session(
        self,
        *,
        workspace_id: str,
        mode: str,
        input_asset_ids: list[str],
        primary_input_asset_id: str,
        companion_asset_ids: list[str] | None = None,
        output_policy: dict | None = None,
    ) -> ProcessingSession:
        with self._lock:
            try:
                return self._get_registry().create_session(
                    workspace_id=workspace_id,
                    mode=mode,
                    input_asset_ids=input_asset_ids,
                    primary_input_asset_id=primary_input_asset_id,
                    companion_asset_ids=companion_asset_ids,
                    output_policy=output_policy,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_session(self, session_id: str) -> ProcessingSession:
        with self._lock:
            try:
                return self._get_registry().get_session(session_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc


_service: SessionService | None = None
_lock = threading.Lock()


def get_session_service() -> SessionService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SessionService()
    return _service
