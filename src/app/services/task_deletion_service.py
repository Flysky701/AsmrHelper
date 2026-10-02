"""Preview and permanently remove selected terminal task history.

File cleanup is deliberately narrower than history cleanup. An artifact path is
an index, not ownership evidence. Unknown/shared paths are always retained.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from uuid import uuid4

from ..errors import AppValidationError


TERMINAL = {"completed", "failed", "cancelled", "skipped"}
MODES = {"history_only", "history_and_files"}


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _key(value):
    return str(Path(value).expanduser().resolve()).casefold()


def _paths(value):
    """Include dictionary keys: graph asset identities use absolute paths as keys."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _paths(key)
            yield from _paths(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _paths(item)
    elif isinstance(value, str) and value and Path(value).is_absolute():
        yield value


def _file_fact(path: Path):
    """Reject directories, aliases and every linked ancestor before opening."""
    if _unsafe_path(path):
        raise ValueError("unsafe or non-local path")
    for ancestor in (path, *path.parents):
        facts = ancestor.lstat()
        if stat.S_ISLNK(facts.st_mode) or getattr(facts, "st_file_attributes", 0) & 0x400:
            raise ValueError("symbolic link or reparse point is retained")
    facts = path.lstat()
    if not stat.S_ISREG(facts.st_mode):
        raise ValueError("only individual regular generated files can be deleted")
    if facts.st_nlink != 1:
        raise ValueError("hard-linked or shared file is retained")
    keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (facts.st_dev, facts.st_ino):
            raise ValueError("file changed while checking ownership")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        checked = os.fstat(stream.fileno())
        if any(getattr(opened, key) != getattr(checked, key) for key in keys):
            raise ValueError("file changed while checking ownership")
    after = path.lstat()
    if any(getattr(facts, key) != getattr(after, key) for key in keys):
        raise ValueError("file changed while checking ownership")
    # Windows path stat and CRT handle stat expose different ctime semantics.
    # Compare the same handle-stat representation at preview and disposition;
    # path stats above independently detect replacement during the hash read.
    return {**{key: getattr(opened, key) for key in keys}, "sha256": digest.hexdigest()}


def _unsafe_path(path):
    return (not path.is_absolute() or ".." in path.parts or str(path).startswith(("\\\\", "//"))
            or any(":" in part or part.endswith((" ", ".")) for part in path.parts[1:]))


def _delete_verified_file(path: Path, expected: dict) -> None:
    """Delete the verified Windows file handle while holding its ancestors.

No path-based unlink fallback: ancestor handles deny renames/reparse replacement,
and the file handle denies writes/renames until disposition is committed.
"""
    if os.name != "nt":
        raise ValueError("safe file deletion is unavailable on this platform; retained")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    invalid = ctypes.c_void_p(-1).value

    class Information(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    def open_handle(value, access, sharing, flags):
        handle = kernel.CreateFileW(str(value), access, sharing, None, 3, flags, None)
        if handle == invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Information()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            code = ctypes.get_last_error()
            kernel.CloseHandle(handle)
            raise ctypes.WinError(code)
        if info.attributes & 0x400:
            kernel.CloseHandle(handle)
            raise ValueError("symbolic link or reparse point was retained")
        return handle, info

    ancestors = []
    handle = None
    try:
        if _unsafe_path(path):
            raise ValueError("unsafe or non-local path")
        for parent in reversed(path.parents):
            parent_handle, _ = open_handle(parent, 0x80, 3, 0x02200000)
            ancestors.append(parent_handle)
        handle, info = open_handle(path, 0x80010000, 1, 0x00200000)
        if info.attributes & 0x10 or info.links != 1:
            raise ValueError("directory or hard-linked file was retained")
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        handle = None  # descriptor owns the native handle from this point
        with os.fdopen(fd, "rb") as stream:
            facts = os.fstat(stream.fileno())
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            actual = {key: getattr(facts, key) for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            actual["sha256"] = digest.hexdigest()
            if actual != expected:
                raise ValueError("file changed since preview; retained")
            disposition = wintypes.BOOL(True)
            if not kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(stream.fileno()), 4,
                    ctypes.byref(disposition), ctypes.sizeof(disposition)):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        for parent_handle in reversed(ancestors):
            kernel.CloseHandle(parent_handle)


class TaskDeletionService:
    PREVIEW_SECONDS = 600

    def __init__(self, *, tasks, artifacts, batches, dispatcher, state_store,
                 inputs=None, protection_loader=None, clock=time.monotonic):
        self.tasks, self.artifacts, self.batches = tasks, artifacts, batches
        self.dispatcher, self.store, self.inputs = dispatcher, state_store, inputs
        self.protection_loader = protection_loader or (lambda: {"paths": [], "roots": []})
        self.clock = clock
        self._lock = threading.RLock()
        self._previews = {}
        self._completed = {}

    @contextmanager
    def _guard(self):
        # Match batch submission's order; dispatcher also acquires the task lock.
        from src.core.speech.store import reference_file_guard
        with ExitStack() as stack:
            stack.enter_context(reference_file_guard())
            for service in (self.batches, self.dispatcher, self.tasks, self.artifacts):
                stack.enter_context(service.history_deletion_guard())
            if self.inputs is not None:
                stack.enter_context(self.inputs.history_deletion_guard())
            yield

    def preview(self, task_ids: list[str], mode: str) -> dict:
        if mode not in MODES or not 1 <= len(task_ids) <= 500 or any(not isinstance(t, str) or not t.strip() for t in task_ids):
            raise AppValidationError("select 1 to 500 task IDs and a supported deletion mode")
        task_ids = list(dict.fromkeys(task_ids))
        with self._lock, self._guard():
            self._previews = {key: value for key, value in self._previews.items() if value["deadline"] > self.clock()}
            plan = self._build(task_ids, mode)
            preview_id = uuid4().hex
            response = {"preview_id": preview_id, "mode": mode,
                        "expires_at": (datetime.now(UTC) + timedelta(seconds=self.PREVIEW_SECONDS)).isoformat(),
                        "can_execute": all(item["eligible"] for item in plan["tasks"]),
                        "tasks": plan["tasks"], "summary": self._preview_summary(plan["tasks"])}
            self._previews[preview_id] = {"deadline": self.clock() + self.PREVIEW_SECONDS,
                "ids": task_ids, "mode": mode, "signature": plan["signature"], "response": response,
                "facts": plan["facts"]}
            return deepcopy(response)

    def execute(self, preview_id: str, *, confirm: bool) -> dict:
        if confirm is not True:
            raise AppValidationError("explicit confirmation is required")
        with self._lock, self._guard():
            if preview_id in self._completed:
                return deepcopy(self._completed[preview_id])
            receipt = self.store.deletion_receipt(preview_id)
            if receipt is not None:
                return receipt
            preview = self._previews.get(preview_id)
            if preview is None or preview["deadline"] <= self.clock():
                raise AppValidationError("deletion preview expired or unavailable; preview again")
            current = self._build(preview["ids"], preview["mode"])
            if not preview["response"]["can_execute"] or not all(item["eligible"] for item in current["tasks"]):
                return self._blocked(preview_id, preview, current, "selection contains active or unavailable tasks; preview again")
            if current["signature"] != preview["signature"]:
                return self._blocked(preview_id, preview, current, "task history or file ownership changed; preview again")
            task_ids = set(preview["ids"])
            records = self.batches.prepare_history_deletion(task_ids)
            results = []
            for item in current["tasks"]:
                files = [{"path": file["path"], "status": "failed" if file["action"] == "delete" else "retained",
                          "reason": "cleanup interrupted before its outcome was recorded" if file["action"] == "delete" else file["reason"]}
                         for file in item["files"]]
                results.append({"task_id": item["task_id"], "history_deleted": True,
                                "status": "partial" if any(f["status"] == "failed" for f in files) else "deleted",
                                "reason": None, "files": files})
            response = {"preview_id": preview_id, "mode": preview["mode"], "results": results,
                        "summary": self._result_summary(results)}
            try:
                self.store.delete_task_history(task_ids, batches=records, receipt=response)
            except Exception as exc:
                for result in results:
                    result.update(history_deleted=False, status="failed", reason=f"history was not deleted: {exc}")
                    for file in result["files"]:
                        file.update(status="retained", reason="history transaction failed; files were not touched")
                response["summary"] = self._result_summary(results)
                return response
            self.tasks.forget_task_history(task_ids)
            self.artifacts.forget_task_history(task_ids)
            self.batches.apply_history_deletion(records, task_ids)
            self.dispatcher.forget_history(task_ids)
            for result, item in zip(results, current["tasks"], strict=False):
                for output, file in zip(result["files"], item["files"], strict=False):
                    if file["action"] != "delete":
                        continue
                    path = Path(file["path"])
                    try:
                        _delete_verified_file(path, preview["facts"][file["path"]])
                    except (OSError, ValueError) as exc:
                        output.update(status="failed", reason=str(exc))
                    else:
                        output.update(status="deleted", reason=None)
                    result["status"] = "partial" if any(f["status"] == "failed" for f in result["files"]) else "deleted"
                    result["reason"] = "history deleted; some files could not be deleted" if result["status"] == "partial" else None
                    response["summary"] = self._result_summary(results)
                    self._save_receipt(response)
            response["summary"] = self._result_summary(results)
            self._save_receipt(response)
            self._completed[preview_id] = deepcopy(response)
            self._previews.pop(preview_id, None)
            return deepcopy(response)

    def _save_receipt(self, response):
        """A later receipt failure cannot turn committed history deletion into 500."""
        try:
            self.store.save_deletion_receipt(response)
        except Exception:
            for result in response["results"]:
                if result["history_deleted"]:
                    result["status"] = "partial"
                    result["reason"] = "history deleted; durable cleanup receipt update failed; file results below describe this request"
            response["summary"] = self._result_summary(response["results"])

    def _blocked(self, preview_id, preview, current, reason):
        results = [{"task_id": item["task_id"], "history_deleted": False, "status": "blocked",
                    "reason": item["reason"] or reason,
                    "files": [{"path": f["path"], "status": "retained", "reason": reason} for f in item["files"]]}
                   for item in current["tasks"]]
        return {"preview_id": preview_id, "mode": preview["mode"], "results": results,
                "summary": self._result_summary(results)}

    def _build(self, task_ids, mode):
        from src.utils import sanitize_filename

        inventory = self.store.deletion_inventory()
        live = {status.task_id: {"spec": asdict(spec), "status": asdict(status)} for spec, status in self.tasks.history_snapshot()}
        persisted = {value["status"]["task_id"]: value for value in inventory["tasks"]}
        all_tasks = {**persisted, **live}
        batches = self.batches.history_snapshot()
        artifacts = {item["artifact_id"]: item for item in inventory["artifacts"]}
        artifacts.update({item.artifact_id: asdict(item) for item in self.artifacts.list_records()})
        owners, candidates, checkpoint_facts, canonical_paths = {}, {}, {}, {}
        def add_candidate(owner, raw, kind):
            if not isinstance(raw, str) or not raw:
                return
            try:
                key = _key(raw)
            except (OSError, ValueError):
                key = raw.casefold()
            owners.setdefault(key, set()).add(owner)
            raw = canonical_paths.setdefault(owner, {}).setdefault(key, raw)
            candidates.setdefault(owner, {}).setdefault(raw, set()).add(kind)
        for item in artifacts.values():
            add_candidate(item["task_id"], item["path"], "artifact")
        for checkpoint in inventory["checkpoints"]:
            for file in checkpoint["record"].get("files", []):
                raw = file.get("path")
                add_candidate(checkpoint["task_id"], raw, "checkpoint")
                if raw:
                    checkpoint_facts[(checkpoint["task_id"], raw)] = (checkpoint["record"].get("producer_task_id"), file)
        protected, protected_roots, reference_error = set(), [], None
        if self.inputs is not None:
            for asset in self.inputs.list_assets():
                protected.add(_key(asset.absolute_path))
                if asset.kind == "folder":
                    protected_roots.append(Path(asset.absolute_path).resolve())
        for value in all_tasks.values():
            source_paths = list(_paths(value["spec"].get("execution_profile", {})))
            protected.update(_key(path) for path in source_paths)
            protected_roots.extend(Path(path).resolve() for path in source_paths if Path(path).is_dir())
            if self.inputs is not None:
                for asset_id in [value["spec"].get("input_asset_id"), *value["spec"].get("companion_asset_ids", [])]:
                    if asset_id:
                        try:
                            protected.add(_key(self.inputs.get_asset(asset_id).absolute_path))
                        except (ValueError, AppValidationError):
                            pass
        for manifest in inventory["manifests"].values():
            protected.update(_key(path) for path in [manifest.get("input_path"), *manifest.get("companion_paths", [])] if path)
        for batch in batches:
            for item in batch.items:
                protected.update(_key(path) for path in [item.input_path, *item.companion_paths, *_paths(item.bindings)] if path)
                if item.current_task_id not in task_ids and item.output_path and Path(item.output_path).is_absolute():
                    protected.add(_key(item.output_path))
        # A remaining recovery consumer can still depend on a deleted producer's copies.
        recovery_consumers = {m.get("resume_of_task_id") for owner, m in inventory["manifests"].items() if owner not in task_ids}
        try:
            evidence = self.protection_loader()
            protected.update(_key(path) for path in evidence.get("paths", []))
            protected_roots.extend(Path(path).resolve() for path in evidence.get("roots", []) if path)
        except Exception:
            reference_error = "reference/model ownership evidence is unavailable; file retained"
        rows, facts, selected_facts = [], {}, []
        for task_id in task_ids:
            value = live.get(task_id)
            state = value["status"]["state"] if value else None
            active_consumers = [owner for owner, candidate in all_tasks.items() if owner != task_id
                and (candidate["status"].get("state") not in TERMINAL or self.dispatcher.has_live_worker(owner))
                and (candidate["spec"].get("retry_of_task_id") == task_id
                     or inventory["manifests"].get(owner, {}).get("resume_of_task_id") == task_id)]
            batch_consumers = any(task_id in item.task_ids and item.state in {"pending", "running"}
                                  for batch in batches for item in batch.items)
            reason = ("task history is unavailable or already deleted" if value is None or task_id not in persisted else
                      "pending/running tasks cannot be deleted" if state not in TERMINAL else
                      "an active retry/resume depends on this history; finish it before deleting" if active_consumers else
                      "an active batch attempt depends on this history; finish it before deleting" if batch_consumers else
                      "task worker is still exiting; preview again" if self.dispatcher.has_live_worker(task_id) else None)
            batch_ids = [batch.batch_id for batch in batches if any(task_id in item.task_ids or task_id == item.current_task_id for item in batch.items)]
            row = {"task_id": task_id, "state": state, "eligible": reason is None, "reason": reason,
                   "batch_ids": batch_ids, "files": []}
            manifest = inventory["manifests"].get(task_id, {})
            owned_root = None
            if value and value["spec"].get("task_type") == "pipeline" and manifest.get("input_path") and manifest.get("output_root"):
                root = Path(manifest["output_root"])
                # Batch-root overrides are not inferred from an arbitrary profile.
                if root.is_absolute():
                    owned_root = root / (sanitize_filename(task_id) or "task") / (sanitize_filename(Path(manifest["input_path"]).stem) or "input")
            for raw, kinds in candidates.get(task_id, {}).items():
                entry = {"path": raw, "action": "retain", "reason": None, "size_bytes": None}
                path = Path(raw)
                try:
                    key, resolved = _key(raw), path.resolve()
                    if mode == "history_only":
                        entry["reason"] = "history-only mode preserves files"
                    elif reason:
                        entry["reason"] = "task is not eligible for deletion"
                    elif reference_error:
                        entry["reason"] = reference_error
                    elif key in protected or any(resolved == root or resolved.is_relative_to(root) for root in protected_roots):
                        entry["reason"] = "input, reference, model or protected file is retained"
                    elif len(owners.get(key, set())) != 1:
                        entry["reason"] = "file is shared by multiple task records"
                    else:
                        checkpoint = checkpoint_facts.get((task_id, raw))
                        checkpoint_root = self.store.db_path.parent / "stage-checkpoints"
                        relative = resolved.relative_to(checkpoint_root.resolve()) if resolved.is_relative_to(checkpoint_root.resolve()) else None
                        checkpoint_owned = (checkpoint is not None and checkpoint[0] == task_id and relative is not None
                            and len(relative.parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", relative.parts[0]) is not None
                            and task_id not in recovery_consumers)
                        artifact_owned = "artifact" in kinds and owned_root is not None and resolved.is_relative_to(owned_root.resolve())
                        if not checkpoint_owned and not artifact_owned:
                            entry["reason"] = "exclusive generated-file ownership cannot be established"
                        else:
                            fact = _file_fact(path)
                            if checkpoint_owned and (fact["sha256"] != checkpoint[1].get("sha256") or fact["st_size"] != checkpoint[1].get("size")):
                                raise ValueError("checkpoint contents changed; retained")
                            entry.update(action="delete", reason="exclusive task output" if artifact_owned else "exclusive recovery copy", size_bytes=fact["st_size"])
                            facts[raw] = fact
                except FileNotFoundError:
                    entry["reason"] = "file is already missing"
                except (OSError, ValueError) as exc:
                    entry["reason"] = str(exc)
                row["files"].append(entry)
            rows.append(row)
            selected_facts.append({"live": value, "persisted": persisted.get(task_id), "manifest": manifest,
                "artifacts": [a for a in artifacts.values() if a["task_id"] == task_id],
                "checkpoints": [c for c in inventory["checkpoints"] if c["task_id"] == task_id],
                "batches": [asdict(batch) for batch in batches if batch.batch_id in batch_ids]})
        return {"tasks": rows, "facts": facts, "signature": _fingerprint({"rows": rows, "facts": facts, "selected": selected_facts})}

    @staticmethod
    def _preview_summary(rows):
        files = [file for row in rows for file in row["files"]]
        return {"selected_count": len(rows), "eligible_count": sum(r["eligible"] for r in rows),
                "blocked_count": sum(not r["eligible"] for r in rows),
                "delete_file_count": sum(f["action"] == "delete" for f in files),
                "retain_file_count": sum(f["action"] == "retain" for f in files),
                "delete_bytes": sum(f["size_bytes"] or 0 for f in files if f["action"] == "delete")}

    @staticmethod
    def _result_summary(rows):
        files = [file for row in rows for file in row["files"]]
        return {**{f"{state}_count": sum(row["status"] == state for row in rows) for state in ("deleted", "blocked", "failed", "partial")},
                **{f"{state}_file_count": sum(file["status"] == state for file in files) for state in ("deleted", "retained", "failed")}}


_service = None
_lock = threading.Lock()


def _protection_evidence(project_root: Path, configured_paths: dict) -> dict:
    """Read only small persistent/staged reference records, never audio/models."""
    voice_root = project_root / "config" / "voice_lab"
    record_path = voice_root / "store.json"
    values = {}
    if record_path.exists():
        _file_fact(record_path)
        values = json.loads(record_path.read_text(encoding="utf-8"))
        if (not isinstance(values, dict) or values.get("schema_version") != 1
                or not isinstance(values.get("collections"), dict)
                or any(not isinstance(records, dict) or any(not isinstance(item, dict) for item in records.values())
                       for records in values["collections"].values())):
            raise ValueError("unsupported or corrupt speech reference metadata")
    paths = list(_paths(values))
    staging = voice_root / "_staging"
    for record in staging.glob("*/inspection.json"):
        if record.is_symlink() or record.parent.is_symlink() or record.parent.resolve().parent != staging.resolve():
            raise ValueError("staged reference metadata uses a link")
        inspection = json.loads(record.read_text(encoding="utf-8"))
        _file_fact(record)
        if (not isinstance(inspection, dict) or not isinstance(inspection.get("original_path"), str)
                or not Path(inspection["original_path"]).is_absolute()
                or inspection.get("companion_source_path") is not None and (
                    not isinstance(inspection["companion_source_path"], str) or not Path(inspection["companion_source_path"]).is_absolute())
                or not isinstance(inspection.get("companion_subtitles", []), list)):
            raise ValueError("corrupt staged reference metadata")
        paths.extend(_paths(inspection))
        source = inspection.get("companion_source_path")
        if source and Path(source).is_absolute():
            for subtitle in inspection.get("companion_subtitles", []):
                if not isinstance(subtitle, dict):
                    raise ValueError("corrupt staged subtitle metadata")
                name = subtitle.get("name", "")
                if name and name == Path(name).name and not any(char in name for char in ("/", "\\", ":")):
                    paths.append(str(Path(source).parent / name))
    roots = [project_root / "config", project_root / "models", voice_root]
    roots.extend(Path(value) for key, value in configured_paths.items() if value and "model" in key)
    roots.extend(Path(path) for path in paths if Path(path).is_dir())
    return {"paths": paths, "roots": roots}


def get_task_deletion_service():
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                from .task_service import get_task_service, get_task_dispatcher
                from .artifact_service import get_artifact_service
                from .batch_run_service import get_batch_run_service
                from .input_catalog_service import get_input_catalog_service
                from ..persistence import get_state_store
                from src.config import PROJECT_ROOT, config

                def protection():
                    return _protection_evidence(PROJECT_ROOT, config.get("paths", {}))

                _service = TaskDeletionService(tasks=get_task_service(), artifacts=get_artifact_service(),
                    batches=get_batch_run_service(), dispatcher=get_task_dispatcher(), state_store=get_state_store(),
                    inputs=get_input_catalog_service(), protection_loader=protection)
    return _service
