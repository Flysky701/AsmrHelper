"""Durable stage recovery facts; no credentials or in-stage progress."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def file_identity(path: str | Path) -> dict:
    source = Path(path).resolve()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(source), "size": source.stat().st_size, "sha256": digest.hexdigest()}


class RecoveryStore:
    """Use the task database transaction boundary for manifests/checkpoints."""

    def __init__(self, state_store):
        self.state_store = state_store
        self.root = state_store.db_path.parent / "stage-checkpoints"
        with state_store._lock, state_store._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS recovery_manifests (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE CASCADE,
                    record_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stage_checkpoints (
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL, record_json TEXT NOT NULL,
                    PRIMARY KEY(task_id, stage)
                );
            """)

    def save_manifest(self, task_id: str, record: dict) -> None:
        with self.state_store._lock, self.state_store._connect() as connection:
            connection.execute("INSERT INTO recovery_manifests VALUES (?, ?) "
                               "ON CONFLICT(task_id) DO UPDATE SET record_json=excluded.record_json",
                               (task_id, json.dumps(record, ensure_ascii=False)))

    def manifest(self, task_id: str) -> dict | None:
        with self.state_store._lock, self.state_store._connect() as connection:
            row = connection.execute("SELECT record_json FROM recovery_manifests WHERE task_id=?",
                                     (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def checkpoint(self, task_id: str, stage: str) -> dict | None:
        with self.state_store._lock, self.state_store._connect() as connection:
            row = connection.execute("SELECT record_json FROM stage_checkpoints WHERE task_id=? AND stage=?",
                                     (task_id, stage)).fetchone()
        return json.loads(row[0]) if row else None

    def commit(self, task_id: str, stage: str, stage_fingerprint: str,
               payload: dict, outputs: list[str]) -> dict:
        """Publish immutable copies before committing the successful stage fact.

        A crash leaves at most an unreferenced directory; it cannot publish a
        checkpoint pointing at partially written files.
        """
        directory = self.root / uuid4().hex
        directory.mkdir(parents=True)
        files = []
        try:
            for index, output in enumerate(dict.fromkeys(outputs)):
                original = Path(output).resolve()
                destination = directory / f"{index}-{original.name}"
                shutil.copyfile(original, destination)
                identity = file_identity(destination)
                if identity["size"] == 0:
                    raise ValueError(f"empty stage output: {original.name}")
                files.append({"original": str(original), **identity})
            record = {"version": 1, "stage": stage, "fingerprint": stage_fingerprint,
                      "producer_task_id": task_id, "completed_at": datetime.now(UTC).isoformat(),
                      "payload": deepcopy(payload), "files": files}
            with self.state_store._lock, self.state_store._connect() as connection:
                connection.execute("INSERT INTO stage_checkpoints VALUES (?, ?, ?) "
                                   "ON CONFLICT(task_id,stage) DO UPDATE SET record_json=excluded.record_json",
                                   (task_id, stage, json.dumps(record, ensure_ascii=False)))
            return record
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def validated(self, task_id: str, stage: str, stage_fingerprint: str) -> dict | None:
        record = self.checkpoint(task_id, stage)
        if not record or record.get("version") != 1 or record.get("fingerprint") != stage_fingerprint:
            return None
        try:
            for item in record["files"]:
                actual = file_identity(item["path"])
                if actual["sha256"] != item["sha256"] or actual["size"] != item["size"]:
                    return None
        except (OSError, KeyError, TypeError):
            return None
        return record

    def retain_interrupted(self) -> None:
        """Keep recoverable unfinished tasks as failed, with a precise cause."""
        with self.state_store._lock, self.state_store._connect() as connection:
            rows = connection.execute("SELECT tasks.task_id, status_json, spec_json FROM tasks "
                "JOIN recovery_manifests USING(task_id) WHERE state NOT IN "
                "('completed','failed','cancelled','skipped')").fetchall()
            for row in rows:
                status = json.loads(row["status_json"])
                graph = json.loads(row["spec_json"]).get("execution_profile", {}).get("version") == 2
                now = datetime.now(UTC).isoformat()
                status.update(state="failed", updated_at=now, finished_at=now,
                              message=("图任务已中断，请检查记录后重新提交；不支持阶段续跑" if graph
                                       else "运行已中断，可从已完成阶段继续"),
                              error={"code": "TASK_INTERRUPTED", "stage": status.get("stage") or "prepare",
                                     "message": "应用停止时任务尚未完成", "retryable": True})
                connection.execute("UPDATE tasks SET state='failed',updated_at=?,status_json=? WHERE task_id=?",
                                   (now, json.dumps(status, ensure_ascii=False), row["task_id"]))
