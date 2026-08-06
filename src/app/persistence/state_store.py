"""SQLite persistence for task history and artifact indexes."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import threading

from src.core.artifacts import ArtifactRecord
from src.core.tasks import TaskSpec, TaskStatus


TERMINAL_STATES = ("completed", "failed", "cancelled", "skipped")


def _with_task_v1_defaults(payload: dict) -> dict:
    """Read pre-retry Task V1 records without changing the stored history."""
    payload.setdefault("retry_of_task_id", None)
    return payload


def _default_state_db_path() -> Path:
    override = os.environ.get("ASMR_HELPER_STATE_DB", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "AsmrHelper" / "state.sqlite3"

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "asmr-helper" / "state.sqlite3"

    return Path.home() / ".local" / "share" / "asmr-helper" / "state.sqlite3"


class SqliteStateStore:
    """Persist task facts and artifact records in one local SQLite database."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    status_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_state_created
                    ON tasks(state, created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task
                    ON artifacts(task_id);
                """
            )

    def save_task(self, task_spec: TaskSpec, task_status: TaskStatus) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, task_type, state, created_at, updated_at,
                    spec_json, status_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_type = excluded.task_type,
                    state = excluded.state,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    spec_json = excluded.spec_json,
                    status_json = excluded.status_json
                """,
                (
                    task_status.task_id,
                    task_status.task_type,
                    task_status.state,
                    task_status.created_at,
                    task_status.updated_at,
                    json.dumps(asdict(task_spec), ensure_ascii=False),
                    json.dumps(asdict(task_status), ensure_ascii=False),
                ),
            )

    def purge_unfinished(self) -> int:
        placeholders = ", ".join("?" for _ in TERMINAL_STATES)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM tasks WHERE state NOT IN ({placeholders})",
                TERMINAL_STATES,
            )
            return cursor.rowcount

    def load_terminal_tasks(self) -> list[tuple[TaskSpec, TaskStatus]]:
        placeholders = ", ".join("?" for _ in TERMINAL_STATES)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT spec_json, status_json
                FROM tasks
                WHERE state IN ({placeholders})
                ORDER BY created_at, task_id
                """,
                TERMINAL_STATES,
            ).fetchall()
        return [
            (
                TaskSpec(**_with_task_v1_defaults(json.loads(row["spec_json"]))),
                TaskStatus(**_with_task_v1_defaults(json.loads(row["status_json"]))),
            )
            for row in rows
        ]
    def save_artifact(self, record: ArtifactRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (artifact_id, task_id, record_json)
                VALUES (?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    record_json = excluded.record_json
                """,
                (
                    record.artifact_id,
                    record.task_id,
                    json.dumps(asdict(record), ensure_ascii=False),
                ),
            )

    def load_terminal_artifacts(self) -> list[ArtifactRecord]:
        placeholders = ", ".join("?" for _ in TERMINAL_STATES)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT artifacts.record_json
                FROM artifacts
                INNER JOIN tasks ON tasks.task_id = artifacts.task_id
                WHERE tasks.state IN ({placeholders})
                ORDER BY artifacts.rowid
                """,
                TERMINAL_STATES,
            ).fetchall()
        return [ArtifactRecord(**json.loads(row["record_json"])) for row in rows]


_store: SqliteStateStore | None = None
_store_path: Path | None = None
_lock = threading.Lock()


def get_state_store() -> SqliteStateStore:
    global _store, _store_path
    resolved_path = _default_state_db_path()
    if _store is None or _store_path != resolved_path:
        with _lock:
            if _store is None or _store_path != resolved_path:
                _store = SqliteStateStore(resolved_path)
                _store_path = resolved_path
    return _store
