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


_FILE_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}


def file_identity(path: str | Path) -> dict:
    source = Path(path).resolve()
    stat = source.stat()
    cache_key = (str(source), stat.st_mtime_ns, stat.st_size)
    cached = _FILE_DIGEST_CACHE.get(cache_key)
    if cached is None:
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        cached = digest.hexdigest()
        if len(_FILE_DIGEST_CACHE) >= 512:
            _FILE_DIGEST_CACHE.pop(next(iter(_FILE_DIGEST_CACHE)))
        _FILE_DIGEST_CACHE[cache_key] = cached
    return {"path": str(source), "size": stat.st_size, "sha256": cached}


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

    def graph_checkpoint_source(self, task_id: str | None, node_id: str) -> str | None:
        visited = set()
        while task_id and task_id not in visited:
            if self.checkpoint(task_id, node_id):
                return task_id
            visited.add(task_id)
            task_id = (self.manifest(task_id) or {}).get("resume_of_task_id")
        return None

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
                              message=("图任务已中断，可查看已完成节点并恢复" if graph
                                       else "V1 任务已中断，历史记录已保留"),
                              error={"code": "TASK_INTERRUPTED", "stage": status.get("stage") or "prepare",
                                     "message": "应用停止时任务尚未完成", "retryable": True})
                connection.execute("UPDATE tasks SET state='failed',updated_at=?,status_json=? WHERE task_id=?",
                                   (now, json.dumps(status, ensure_ascii=False), row["task_id"]))

class GraphCheckpoints:
    """Store validated node outputs under the immutable submission and restore into a fresh attempt."""

    def __init__(self, store, task_id, profile):
        self.store = store
        self.task_id = task_id
        self.signature = fingerprint(profile)
        manifest = store.manifest(task_id) or {}
        self.previous = manifest.get("resume_of_task_id")

    def restore(self, node_id, directory):
        from src.core.orchestration.pipeline.graph_adapters import GraphValue

        source_task = self.store.graph_checkpoint_source(self.previous, node_id)
        if source_task is None:
            return None
        record = self.store.validated(source_task, node_id, self.signature)
        if record is None:
            raise ValueError(f"节点 {node_id} 的恢复文件已改变，请重新提交任务")
        originals = {f["original"]: f["path"] for f in record["files"]}
        directory.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for port, raw in record["payload"].items():
            src = originals[raw["path"]]
            dest = directory / Path(raw["path"]).name
            shutil.copyfile(src, dest)
            outputs[port] = GraphValue(**{**raw, "path": str(dest)})
        return outputs

    def save(self, node_id, outputs):
        from dataclasses import asdict
        payload = {port: {**asdict(value), "path": str(Path(value.path).resolve())}
                   for port, value in outputs.items()}
        self.store.commit(self.task_id, node_id, self.signature, payload, [v["path"] for v in payload.values()])
