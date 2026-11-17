"""SQLite persistence for two-phase DraftSession state and optimistic concurrency."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from src.app.errors import AppValidationError, ResourceUnavailableError
from src.app.persistence.state_store import SqliteStateStore, get_state_store


DRAFT_STATES = (
    "preparing",
    "awaiting_review",
    "committing",
    "completed",
    "failed",
)


class DraftConflictError(AppValidationError, ValueError):
    """Raised when an optimistic revision check fails during patch or commit."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_state(state: str) -> str:
    if state not in DRAFT_STATES:
        raise AppValidationError(f"Unsupported draft state: {state!r}")
    return state


def _validate_expected_revision(expected_revision: int | None) -> int | None:
    if expected_revision is None:
        return None
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
        raise AppValidationError("expected_revision must be a positive integer")
    return expected_revision


@dataclass(slots=True)
class DraftRecord:
    """Typed in-memory projection of a persisted `draft_sessions` row."""

    draft_id: str
    state: str
    work_dir: str
    title: str
    tracks: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    voice_plan: dict[str, Any]
    audit_report: dict[str, Any]
    artifacts: dict[str, Any]
    revision: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "state": self.state,
            "work_dir": self.work_dir,
            "title": self.title,
            "tracks": deepcopy(self.tracks),
            "segments": deepcopy(self.segments),
            "voice_plan": deepcopy(self.voice_plan),
            "audit_report": deepcopy(self.audit_report),
            "artifacts": deepcopy(self.artifacts),
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class DraftStore:
    """Persist two-phase `DraftSession` records inside `SqliteStateStore.db_path`."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        state_store: SqliteStateStore | None = None,
    ) -> None:
        if db_path is not None:
            resolved = Path(db_path).expanduser().resolve()
        elif state_store is not None:
            resolved = state_store.db_path
        else:
            resolved = get_state_store().db_path
        self.db_path = resolved
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS draft_sessions (
                    draft_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    work_dir TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tracks_json TEXT NOT NULL,
                    segments_json TEXT NOT NULL,
                    voice_plan_json TEXT NOT NULL,
                    audit_report_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_draft_sessions_state_updated
                    ON draft_sessions(state, updated_at DESC);
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DraftRecord:
        return DraftRecord(
            draft_id=str(row["draft_id"]),
            state=str(row["state"]),
            work_dir=str(row["work_dir"]),
            title=str(row["title"]),
            tracks=json.loads(row["tracks_json"]),
            segments=json.loads(row["segments_json"]),
            voice_plan=json.loads(row["voice_plan_json"]),
            audit_report=json.loads(row["audit_report_json"]),
            artifacts=json.loads(row["artifacts_json"]),
            revision=int(row["revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def create_draft(
        self,
        *,
        draft_id: str,
        state: str = "preparing",
        work_dir: str,
        title: str,
        tracks: list[dict[str, Any]] | None = None,
        segments: list[dict[str, Any]] | None = None,
        voice_plan: dict[str, Any] | None = None,
        audit_report: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        revision: int = 1,
    ) -> DraftRecord:
        _validate_state(state)
        if not draft_id or not str(draft_id).strip():
            raise AppValidationError("draft_id must be non-empty")
        now = _utc_now_iso()
        record = DraftRecord(
            draft_id=str(draft_id).strip(),
            state=state,
            work_dir=str(work_dir),
            title=str(title),
            tracks=deepcopy(tracks or []),
            segments=deepcopy(segments or []),
            voice_plan=deepcopy(voice_plan or {}),
            audit_report=deepcopy(audit_report or {}),
            artifacts=deepcopy(artifacts or {}),
            revision=int(revision),
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO draft_sessions (
                        draft_id, state, work_dir, title,
                        tracks_json, segments_json, voice_plan_json,
                        audit_report_json, artifacts_json,
                        revision, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.draft_id,
                        record.state,
                        record.work_dir,
                        record.title,
                        json.dumps(record.tracks, ensure_ascii=False),
                        json.dumps(record.segments, ensure_ascii=False),
                        json.dumps(record.voice_plan, ensure_ascii=False),
                        json.dumps(record.audit_report, ensure_ascii=False),
                        json.dumps(record.artifacts, ensure_ascii=False),
                        record.revision,
                        record.created_at,
                        record.updated_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DraftConflictError(f"Draft already exists: {record.draft_id}") from exc
        return record

    def get_draft(self, draft_id: str) -> DraftRecord:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM draft_sessions WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        if row is None:
            raise ResourceUnavailableError(f"Draft session not found: {draft_id}")
        return self._row_to_record(row)

    def list_drafts(
        self,
        *,
        state: str | None = None,
        limit: int = 100,
    ) -> list[DraftRecord]:
        if state is not None:
            _validate_state(state)
        bounded_limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as connection:
            if state is not None:
                rows = connection.execute(
                    """
                    SELECT * FROM draft_sessions
                    WHERE state = ?
                    ORDER BY updated_at DESC, created_at DESC, draft_id DESC
                    LIMIT ?
                    """,
                    (state, bounded_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM draft_sessions
                    ORDER BY updated_at DESC, created_at DESC, draft_id DESC
                    LIMIT ?
                    """,
                    (bounded_limit,),
                ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update_draft(
        self,
        draft_id: str,
        *,
        expected_revision: int | None = None,
        increment_revision: bool = True,
        state: str | None = None,
        title: str | None = None,
        tracks: list[dict[str, Any]] | None = None,
        segments: list[dict[str, Any]] | None = None,
        voice_plan: dict[str, Any] | None = None,
        audit_report: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> DraftRecord:
        checked_expected = _validate_expected_revision(expected_revision)
        if state is not None:
            _validate_state(state)

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM draft_sessions WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise ResourceUnavailableError(f"Draft session not found: {draft_id}")

            current = self._row_to_record(row)
            if checked_expected is not None and current.revision != checked_expected:
                raise DraftConflictError(
                    f"Draft {draft_id!r} revision conflict: expected {checked_expected}, current {current.revision}"
                )

            next_state = state if state is not None else current.state
            next_title = title if title is not None else current.title
            next_tracks = deepcopy(tracks) if tracks is not None else current.tracks
            next_segments = deepcopy(segments) if segments is not None else current.segments
            next_voice_plan = deepcopy(voice_plan) if voice_plan is not None else current.voice_plan
            next_audit = deepcopy(audit_report) if audit_report is not None else current.audit_report
            next_artifacts = deepcopy(artifacts) if artifacts is not None else current.artifacts
            next_revision = current.revision + 1 if increment_revision else current.revision
            now = _utc_now_iso()

            cursor = connection.execute(
                """
                UPDATE draft_sessions
                SET state = ?,
                    title = ?,
                    tracks_json = ?,
                    segments_json = ?,
                    voice_plan_json = ?,
                    audit_report_json = ?,
                    artifacts_json = ?,
                    revision = ?,
                    updated_at = ?
                WHERE draft_id = ? AND revision = ?
                """,
                (
                    next_state,
                    next_title,
                    json.dumps(next_tracks, ensure_ascii=False),
                    json.dumps(next_segments, ensure_ascii=False),
                    json.dumps(next_voice_plan, ensure_ascii=False),
                    json.dumps(next_audit, ensure_ascii=False),
                    json.dumps(next_artifacts, ensure_ascii=False),
                    next_revision,
                    now,
                    draft_id,
                    current.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise DraftConflictError(
                    f"Draft {draft_id!r} changed concurrently; reload and retry"
                )

            return DraftRecord(
                draft_id=current.draft_id,
                state=next_state,
                work_dir=current.work_dir,
                title=next_title,
                tracks=next_tracks,
                segments=next_segments,
                voice_plan=next_voice_plan,
                audit_report=next_audit,
                artifacts=next_artifacts,
                revision=next_revision,
                created_at=current.created_at,
                updated_at=now,
            )

    def delete_draft(self, draft_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM draft_sessions WHERE draft_id = ?",
                (draft_id,),
            )
            return cursor.rowcount > 0


_draft_store: DraftStore | None = None
_draft_store_path: Path | None = None
_store_lock = threading.Lock()


def get_draft_store() -> DraftStore:
    """Return a shared `DraftStore` aligned with the active `SqliteStateStore` path."""
    global _draft_store, _draft_store_path
    resolved_path = get_state_store().db_path
    if _draft_store is None or _draft_store_path != resolved_path:
        with _store_lock:
            if _draft_store is None or _draft_store_path != resolved_path:
                _draft_store = DraftStore(resolved_path)
                _draft_store_path = resolved_path
    return _draft_store
