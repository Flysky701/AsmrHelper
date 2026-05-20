"""Processing session service."""

from __future__ import annotations

import threading
from pathlib import Path

from src.utils import ensure_dir, sanitize_filename

from ..dto import ProcessingSession
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
        self._sessions: dict[str, ProcessingSession] = {}
        self._counter = 0
        self._lock = threading.Lock()

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
        workspace = self.workspace_service.resolve()
        if workspace.workspace_id != workspace_id:
            raise AppValidationError(f"unknown workspace id: {workspace_id}")
        if not input_asset_ids:
            raise AppValidationError("input_asset_ids is required")

        primary_asset = self.input_catalog_service.get_asset(primary_input_asset_id)
        output_policy = output_policy or {"mode": "workspace-default", "custom_output_dir": None}
        output_dir = self._resolve_output_dir(workspace.default_output_root, primary_asset.display_name, output_policy)

        with self._lock:
            self._counter += 1
            session_id = f"session-{self._counter}"

        temp_dir = str(ensure_dir(str(Path(workspace.default_temp_root) / session_id)))
        resolved_output = str(ensure_dir(output_dir))
        session = ProcessingSession(
            session_id=session_id,
            workspace_id=workspace_id,
            mode=mode,
            input_asset_ids=list(input_asset_ids),
            primary_input_asset_id=primary_input_asset_id,
            companion_asset_ids=list(companion_asset_ids or []),
            resolved_output_dir=resolved_output,
            resolved_temp_dir=temp_dir,
            status="ready",
            validation={"ok": True, "errors": [], "warnings": []},
        )
        with self._lock:
            self._sessions[session_id] = session
        return self._clone(session)

    def get_session(self, session_id: str) -> ProcessingSession:
        with self._lock:
            try:
                session = self._sessions[session_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown session id: {session_id}") from exc
        return self._clone(session)

    def _resolve_output_dir(self, default_output_root: str, display_name: str, output_policy: dict) -> str:
        mode = output_policy.get("mode", "workspace-default")
        custom = output_policy.get("custom_output_dir")
        if mode == "custom-dir" and custom:
            return str(Path(custom).resolve())
        safe_name = sanitize_filename(Path(display_name).stem or "session")
        return str(Path(default_output_root) / safe_name)

    def _clone(self, session: ProcessingSession) -> ProcessingSession:
        return ProcessingSession(
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            mode=session.mode,
            input_asset_ids=list(session.input_asset_ids),
            primary_input_asset_id=session.primary_input_asset_id,
            companion_asset_ids=list(session.companion_asset_ids),
            resolved_output_dir=session.resolved_output_dir,
            resolved_temp_dir=session.resolved_temp_dir,
            status=session.status,
            validation=dict(session.validation),
        )


_service: SessionService | None = None
_lock = threading.Lock()


def get_session_service() -> SessionService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SessionService()
    return _service
