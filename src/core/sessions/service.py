"""Session registry and output resolution."""

from __future__ import annotations

from pathlib import Path

from src.utils import ensure_dir, sanitize_filename

from .catalog import InputCatalog
from .models import ProcessingSession, WorkspaceContext


class SessionRegistry:
    """Create and resolve processing sessions against a workspace."""

    def __init__(self, *, workspace: WorkspaceContext, input_catalog: InputCatalog) -> None:
        self._workspace = workspace
        self._input_catalog = input_catalog
        self._sessions: dict[str, ProcessingSession] = {}
        self._counter = 0

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
        if self._workspace.workspace_id != workspace_id:
            raise ValueError(f"unknown workspace id: {workspace_id}")
        if not input_asset_ids:
            raise ValueError("input_asset_ids is required")

        primary_asset = self._input_catalog.get_asset(primary_input_asset_id)
        output_policy = output_policy or {"mode": "workspace-default", "custom_output_dir": None}
        output_dir = self._resolve_output_dir(
            self._workspace.default_output_root,
            primary_asset.display_name,
            output_policy,
        )

        self._counter += 1
        session_id = f"session-{self._counter}"
        temp_dir = str(ensure_dir(str(Path(self._workspace.default_temp_root) / session_id)))
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
        self._sessions[session_id] = session
        return self._clone(session)

    def get_session(self, session_id: str) -> ProcessingSession:
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise ValueError(f"unknown session id: {session_id}") from exc
        return self._clone(session)

    @staticmethod
    def _resolve_output_dir(default_output_root: str, display_name: str, output_policy: dict) -> str:
        mode = output_policy.get("mode", "workspace-default")
        custom = output_policy.get("custom_output_dir")
        if mode == "task-scoped-root":
            return str(Path(custom or default_output_root).resolve())
        if mode == "custom-dir" and custom:
            return str(Path(custom).resolve())
        safe_name = sanitize_filename(Path(display_name).stem or "session")
        return str(Path(default_output_root) / safe_name)

    @staticmethod
    def _clone(session: ProcessingSession) -> ProcessingSession:
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
