"""SQLite persistence for task history and artifact indexes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import threading

from src.core.artifacts import ArtifactRecord
from src.core.batches import BatchRunRecord
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back the operation, then release its database handle."""
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

                CREATE TABLE IF NOT EXISTS batch_runs (
                    batch_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deleted_task_ids (
                    task_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS task_deletion_receipts (
                    preview_id TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deleted_batch_runs (
                    batch_id TEXT PRIMARY KEY, client_request_id TEXT, request_fingerprint TEXT
                );
                CREATE TABLE IF NOT EXISTS deleted_artifact_ids (
                    artifact_id TEXT PRIMARY KEY
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_state_created
                    ON tasks(state, created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_task
                    ON artifacts(task_id);
                CREATE INDEX IF NOT EXISTS idx_batch_runs_created
                    ON batch_runs(created_at);
                """
            )

    def save_task(self, task_spec: TaskSpec, task_status: TaskStatus, *, recovery_manifest: dict | None = None) -> None:
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

            if recovery_manifest is not None:
                connection.execute(
                    "INSERT INTO recovery_manifests VALUES (?, ?) "
                    "ON CONFLICT(task_id) DO UPDATE SET record_json=excluded.record_json",
                    (task_spec.task_id, json.dumps(recovery_manifest, ensure_ascii=False)),
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

    def save_batch_run(self, record: BatchRunRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_runs (
                    batch_id, state, created_at, updated_at, record_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    state = excluded.state,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """,
                (
                    record.batch_id,
                    record.state,
                    record.created_at,
                    record.updated_at,
                    json.dumps(asdict(record), ensure_ascii=False),
                ),
            )

    def load_batch_runs(self) -> list[BatchRunRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM batch_runs
                ORDER BY created_at, batch_id
                """
            ).fetchall()
        return [BatchRunRecord.from_dict(json.loads(row["record_json"])) for row in rows]

    def load_deleted_task_ids(self) -> list[str]:
        with self._lock, self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT task_id FROM deleted_task_ids")]

    def load_deleted_artifact_ids(self) -> list[str]:
        with self._lock, self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT artifact_id FROM deleted_artifact_ids")]

    def load_deleted_batches(self) -> list[dict]:
        with self._lock, self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM deleted_batch_runs")]

    def deletion_inventory(self) -> dict:
        """Read ownership evidence; never infer ownership from an artifact path alone."""
        with self._lock, self._connect() as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {
                "tasks": [{"spec": json.loads(row[0]), "status": json.loads(row[1])}
                          for row in connection.execute("SELECT spec_json,status_json FROM tasks")],
                "artifacts": [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM artifacts")],
                "manifests": {row[0]: json.loads(row[1]) for row in connection.execute(
                    "SELECT task_id,record_json FROM recovery_manifests")} if "recovery_manifests" in tables else {},
                "checkpoints": [{"task_id": row[0], "stage": row[1], "record": json.loads(row[2])}
                                for row in connection.execute("SELECT task_id,stage,record_json FROM stage_checkpoints")]
                               if "stage_checkpoints" in tables else [],
            }

    def deletion_receipt(self, preview_id: str) -> dict | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT response_json FROM task_deletion_receipts WHERE preview_id=?", (preview_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_deletion_receipt(self, response: dict) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO task_deletion_receipts VALUES (?, ?) ON CONFLICT(preview_id) DO UPDATE SET response_json=excluded.response_json",
                               (response["preview_id"], json.dumps(response, ensure_ascii=False)))

    def delete_task_history(self, task_ids: set[str], *, batches: list[BatchRunRecord], receipt: dict) -> None:
        """Commit task/index/recovery/batch references and an idempotent receipt together."""
        with self._lock, self._connect() as connection:
            for task_id in task_ids:
                row = connection.execute("SELECT state FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                if row is None or row[0] not in TERMINAL_STATES:
                    raise ValueError(f"task history changed; preview again: {task_id}")
            for task_id in task_ids:
                connection.execute("INSERT OR IGNORE INTO deleted_artifact_ids SELECT artifact_id FROM artifacts WHERE task_id=?", (task_id,))
                connection.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
                connection.execute("INSERT OR IGNORE INTO deleted_task_ids VALUES (?)", (task_id,))
            for row in connection.execute("SELECT task_id,spec_json,status_json FROM tasks").fetchall():
                spec, status = json.loads(row[1]), json.loads(row[2])
                if spec.get("retry_of_task_id") in task_ids or status.get("retry_of_task_id") in task_ids:
                    spec["retry_of_task_id"] = status["retry_of_task_id"] = None
                    connection.execute("UPDATE tasks SET spec_json=?,status_json=? WHERE task_id=?",
                                       (json.dumps(spec, ensure_ascii=False), json.dumps(status, ensure_ascii=False), row[0]))
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "recovery_manifests" in tables:
                for row in connection.execute("SELECT task_id,record_json FROM recovery_manifests").fetchall():
                    manifest = json.loads(row[1])
                    if manifest.get("resume_of_task_id") in task_ids:
                        manifest["resume_of_task_id"] = None
                        connection.execute("UPDATE recovery_manifests SET record_json=? WHERE task_id=?",
                                           (json.dumps(manifest, ensure_ascii=False), row[0]))
            for record in batches:
                if record.state == "history_deleted":
                    connection.execute("DELETE FROM batch_runs WHERE batch_id=?", (record.batch_id,))
                    connection.execute("INSERT OR REPLACE INTO deleted_batch_runs VALUES (?, ?, ?)",
                                       (record.batch_id, record.client_request_id, record.request_fingerprint))
                else:
                    connection.execute("UPDATE batch_runs SET state=?,updated_at=?,record_json=? WHERE batch_id=?",
                                       (record.state, record.updated_at, json.dumps(asdict(record), ensure_ascii=False), record.batch_id))
            connection.execute("INSERT INTO task_deletion_receipts VALUES (?, ?)",
                               (receipt["preview_id"], json.dumps(receipt, ensure_ascii=False)))


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
