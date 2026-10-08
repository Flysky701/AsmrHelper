"""Explicit, conservative and reversible cleanup of VoiceLab-owned data."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from src.core.speech.store import reference_file_guard, _now, _hash_file


def values(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from values(item)
    elif isinstance(value, str):
        yield value


def references(value, ids, paths):
    for item in values(value):
        if item in ids:
            return True
        if paths and ("/" in item or "\\" in item):
            try:
                candidate = Path(item).resolve()
                if any(candidate == path or candidate.is_relative_to(path) for path in paths):
                    return True
            except (ValueError, OSError):
                return True  # Unknown paths are never evidence of no reference.
    return False


def owned_path(root, path):
    """Reject links/junctions in every component, including the managed root."""
    root, path = Path(root).absolute(), Path(path).absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError("路径不属于应用专用子目录")
    for current in (path, *path.parents):
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("链接或联接目录不能清理")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("路径越过应用目录边界")
    return path


def file_manifest(root, paths):
    result = []
    for path in sorted(set(paths), key=str):
        path = owned_path(root, path)
        if not path.exists():
            continue
        children = [path, *path.rglob("*")] if path.is_dir() else [path]
        for child in children:
            owned_path(root, child)
            if child.is_file():
                result.append({"path": str(child), "bytes": child.stat().st_size, "sha256": _hash_file(child)})
    return result


class SpeechCleanupService:
    def __init__(self, speech, catalog=None, batches=None):
        self.speech, self.store = speech, speech.store
        if catalog is None:
            from .preset_catalog_service import get_preset_catalog_service
            catalog = get_preset_catalog_service()
        self.catalog = catalog
        self.batches = batches
        if batches is None and getattr(speech.tasks, "_state_store", None) is not None:
            from .batch_run_service import get_batch_run_service
            self.batches = get_batch_run_service()

    @contextmanager
    def guard(self):
        # Same order as task history deletion: reference capture before task locks.
        from .preset_catalog_service import _write_lock
        with reference_file_guard(), (self.batches.history_deletion_guard() if self.batches else nullcontext()), self.speech.dispatcher.history_deletion_guard(), self.speech.tasks.history_deletion_guard(), self.speech.artifacts.history_deletion_guard():
            with _write_lock, self.store._locked():
                self._recover_interrupted_moves()
                yield

    def _recover_interrupted_moves(self):
        committed = set(self.store._read().get("cleanup_receipts", []))
        for record in (self.store.root / "_trash").glob("*/manifest.json"):
            owned_path(self.store.root, record)
            if record.parent.name in committed:
                continue
            manifest = json.loads(record.read_text(encoding="utf-8"))
            # Restore an interrupted move before metadata committed (or after undo
            # committed). Never replace a newly occupied original path.
            for index, original in enumerate(manifest.get("paths", [])):
                source = owned_path(self.store.root, record.parent / str(index))
                if not source.exists():
                    continue
                target = owned_path(self.store.root, original)
                if target.exists():
                    raise ValueError("中断清理的原路径已占用，文件已保留，请人工检查回收区")
                file_manifest(self.store.root, [source])
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)

    def external(self):
        result = {"tasks": self.speech.tasks.history_snapshot(),
                "artifacts": self.speech.artifacts.list_records(),
                "workflows": self.catalog.list_presets() + self.catalog.list_archived_presets()}
        persisted = getattr(self.speech.tasks, "_state_store", None)
        if persisted is not None:
            result["persistent_history"] = persisted.deletion_inventory()
        if self.batches is not None:
            result["batches"] = self.batches.history_snapshot()
            result["batch_snapshots"] = getattr(self.batches, "_graph_snapshots", {})
        result["recoverable_data"] = [json.loads(
            (owned_path(self.store.root, self.store.root / "_trash" / id) / "manifest.json").read_text(encoding="utf-8"))
            for id in self.store._read().get("cleanup_receipts", [])]
        return result

    def preview(self, kind, item_id="all"):
        with self.guard():
            return self._preview(kind, item_id)[0]

    def _preview(self, kind, item_id):
        if kind == "trash":
            return self._purge_preview(item_id)
        state = self.store._read()
        records = state["collections"]
        selected = {key: {} for key in records}
        paths, blockers = [], []
        external = self.external()
        if any(batch.state not in {"completed", "completed_with_errors", "cancelled", "interrupted", "history_deleted"}
               for batch in external.get("batches", [])):
            blockers.append("存在未结束批任务，请先结束批任务")
        external["store_metadata"] = {key: value for key, value in state.items() if key != "collections"}
        if kind != "staging":
            external["staged_references"] = [json.loads(path.read_text(encoding="utf-8"))
                for path in (self.store.root / "_staging").glob("*/inspection.json")]
        if any(status.state not in {"completed", "failed", "cancelled", "skipped"}
               for _, status in external["tasks"]):
            blockers.append("存在未结束任务；请先等待或取消任务")
        if any(self.speech.dispatcher.has_live_worker(status.task_id) for _, status in external["tasks"]):
            blockers.append("任务工作线程仍在退出，请稍后重试")
        if kind == "experiments":
            experiment = records[kind][item_id]
            if experiment.get("kind") == "formal" or experiment.get("media_root"):
                blockers.append("正式配音及工作台输出由任务历史管理，不能在此清理")
            selected[kind][item_id] = experiment
            for key in ("takes", "selections", "assemblies"):
                selected[key] = {id: row for id, row in records[key].items() if row.get("experiment_id") == item_id}
            plan_ids = {row.get("plan_id") for key in ("experiments", "takes") for row in selected[key].values()}
            for id in plan_ids - {None}:
                remaining = {key: {rid: row for rid, row in rows.items() if rid not in selected[key]}
                             for key, rows in records.items() if key != "plans"}
                if not references(remaining, {id}, []) and not references(external, {id}, []):
                    selected["plans"][id] = records["plans"][id]
            for key in ("takes", "assemblies"):
                for row in selected[key].values():
                    for field in ("audio_path", "mixed_path"):
                        if row.get(field):
                            path = owned_path(self.store.root, row[field])
                            if path.parent.name not in {"takes", "assemblies"} or path.parent.parent != self.store.root:
                                blockers.append("音频不在实验专用目录中")
                            else:
                                paths.append(path)
        elif kind == "recipes":
            root = self.store._recipe_root(records[kind], item_id)
            if not records["rule_states"].get(root, {}).get("archived"):
                blockers.append("请先归档音色")
            selected[kind] = {id: row for id, row in records[kind].items()
                              if self.store._recipe_root(records[kind], id) == root}
            if root in records["rule_states"]:
                selected["rule_states"][root] = records["rule_states"][root]
        elif kind == "assets":
            asset = records[kind][item_id]
            selected[kind][item_id] = asset
            if not asset.get("archived"):
                blockers.append("请先归档录音")
            directory = owned_path(self.store.assets_root, Path(asset["path"]).parent)
            if directory.parent != self.store.assets_root or not re.fullmatch(r"[0-9a-f-]{36}", directory.name):
                blockers.append("无法确认录音目录所有权")
            for field in ("path", "source_path", "source_playback_path"):
                if asset.get(field) and Path(asset[field]).parent != directory:
                    blockers.append("录音文件目录不一致")
            paths.append(directory)
        elif kind == "staging":
            staging = self.store.root / "_staging"
            for directory in sorted(staging.iterdir()) if staging.exists() else []:
                if not re.fullmatch(r"[0-9a-f-]{36}", directory.name):
                    continue
                try:
                    owned_path(self.store.root, directory)
                    self.store.get_inspection(directory.name)
                    # Also retain any staged file referenced by another inspection.
                    others = [json.loads(p.read_text(encoding="utf-8")) for p in staging.glob("*/inspection.json")
                              if p.parent != directory]
                    if not references([state, external, others], {directory.name}, [directory]):
                        paths.append(directory)
                except (ValueError, KeyError, OSError):
                    continue  # Unrecognized/corrupt entries remain untouched.
        else:
            raise ValueError("不支持的清理类型")
        ids = {id for rows in selected.values() for id in rows}
        remaining = {key: {id: row for id, row in rows.items() if id not in selected[key]} for key, rows in records.items()}
        for key, value in {**remaining, **external}.items():
            if references(value, ids, paths):
                label = {"voices": "保存声音", "recipes": "音色规则", "experiments": "试音实验", "takes": "候选音频",
                         "selections": "采用记录", "assemblies": "组装记录", "assets": "参考录音", "plans": "台词",
                         "tasks": "任务历史", "artifacts": "任务产物", "workflows": "工作流", "batches": "批任务",
                         "recoverable_data": "回收区数据", "staged_references": "录音暂存",
                         "persistent_history": "持久任务和恢复记录"}.get(key, "其他保存数据")
                blockers.append(f"仍被{label}引用；请先解除引用或处理对应历史")
        files = file_manifest(self.store.root, paths)
        payload = {"kind": kind, "item_id": item_id, "records": selected,
                   "paths": [str(p) for p in paths], "files": files, "blockers": sorted(set(blockers))}
        token = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"kind": kind, "item_id": item_id, "token": token, "blockers": payload["blockers"],
                "records": {k: len(v) for k, v in selected.items() if v}, "files": files,
                "bytes": sum(f["bytes"] for f in files), "paths": payload["paths"],
                "recoverable": True}, payload

    def execute(self, kind, item_id, token, confirmed=False):
        if confirmed is not True:
            raise ValueError("请预览影响并确认本次清理")
        with self.guard():
            preview, payload = self._preview(kind, item_id)
            if preview["token"] != token:
                raise ValueError("内容或引用已改变，请重新预览")
            if preview["blockers"]:
                raise ValueError("；".join(preview["blockers"]))
            if kind == "trash":
                return self._purge(item_id, payload)
            if not preview["paths"] and not preview["records"]:
                raise ValueError("没有可清理的无引用内容")
            receipt_id = uuid4().hex
            trash = owned_path(self.store.root, self.store.root / "_trash" / receipt_id)
            trash.mkdir(parents=True)
            manifest = {**payload, "id": receipt_id, "created_at": _now(), "state": "prepared"}
            self.store._atomic_json(trash / "manifest.json", manifest)
            moved = []
            try:
                for index, path in enumerate(payload["paths"]):
                    source = owned_path(self.store.root, path)
                    if source.exists():
                        destination = trash / str(index)
                        source.rename(destination)
                        moved.append((source, destination))
                state = self.store._read()
                for key, rows in payload["records"].items():
                    for id in rows:
                        del state["collections"][key][id]
                # Durable commit marker makes crash recovery unambiguous.
                state.setdefault("cleanup_receipts", []).append(receipt_id)
                self.store._write(state)
            except BaseException:
                for source, destination in reversed(moved):
                    destination.rename(source)
                raise
            return {"id": receipt_id, "recoverable": True}

    def receipts(self):
        with self.guard():
            return [{"id": id, **{key: value for key, value in json.loads(
                (owned_path(self.store.root, self.store.root / "_trash" / id) / "manifest.json").read_text(encoding="utf-8")).items()
                if key in {"kind", "item_id", "created_at"}}} for id in self.store._read().get("cleanup_receipts", [])]

    def _purge_preview(self, receipt_id):
        if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
            raise ValueError("无效回收记录")
        state = self.store._read()
        if receipt_id not in state.get("cleanup_receipts", []):
            raise ValueError("回收记录不存在")
        trash = owned_path(self.store.root, self.store.root / "_trash" / receipt_id)
        manifest = json.loads((trash / "manifest.json").read_text(encoding="utf-8"))
        ids = {id for rows in manifest["records"].values() for id in rows}
        paths = [owned_path(self.store.root, value) for value in manifest["paths"]]
        evidence = self.external()
        evidence["recoverable_data"] = [item for item in evidence["recoverable_data"] if item["id"] != receipt_id]
        evidence["speech"] = state["collections"]
        blockers = [f"{key}仍有引用，保留回收内容" for key, value in evidence.items() if references(value, ids, paths)]
        if any(status.state not in {"completed", "failed", "cancelled", "skipped"}
               or self.speech.dispatcher.has_live_worker(status.task_id) for _, status in evidence["tasks"]):
            blockers.append("存在未结束任务或尚未退出的工作线程")
        if any(batch.state not in {"completed", "completed_with_errors", "cancelled", "interrupted", "history_deleted"}
               for batch in evidence.get("batches", [])):
            blockers.append("存在未结束批任务")
        files = file_manifest(self.store.root, [trash])
        payload = {"kind": "trash", "item_id": receipt_id, "blockers": blockers, "files": files,
                   "records": {}, "paths": [str(trash)], "bytes": sum(file["bytes"] for file in files), "recoverable": False}
        payload["token"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return payload, manifest

    def _purge(self, receipt_id, manifest):
        trash = owned_path(self.store.root, self.store.root / "_trash" / receipt_id)
        # Keep the manifest/receipt until every payload is gone, so partial filesystem
        # failures can be reviewed and retried without losing the deletion journal.
        for index in range(len(manifest["paths"])):
            path = owned_path(self.store.root, trash / str(index))
            file_manifest(self.store.root, [path])
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        state = self.store._read()
        state["cleanup_receipts"].remove(receipt_id)
        self.store._write(state)
        (trash / "manifest.json").unlink()
        trash.rmdir()
        return {"purged": receipt_id, "recoverable": False}

    def restore(self, receipt_id):
        if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
            raise ValueError("无效恢复记录")
        with self.guard():
            state = self.store._read()
            if receipt_id not in state.get("cleanup_receipts", []):
                raise ValueError("恢复记录不存在或已恢复")
            trash = owned_path(self.store.root, self.store.root / "_trash" / receipt_id)
            manifest = json.loads((trash / "manifest.json").read_text(encoding="utf-8"))
            for key, rows in manifest["records"].items():
                if set(rows) & set(state["collections"][key]):
                    raise ValueError("记录 ID 已被使用，不能覆盖")
            moves = []
            for index, value in enumerate(manifest["paths"]):
                path = owned_path(self.store.root, value)
                source = owned_path(self.store.root, trash / str(index))
                if path.exists():
                    raise ValueError("原路径已有文件，不能覆盖")
                if source.exists():
                    file_manifest(self.store.root, [source])
                    for file in manifest["files"]:
                        original = Path(file["path"])
                        if original == path or original.is_relative_to(path):
                            saved = source if original == path else source / original.relative_to(path)
                            if not saved.is_file() or _hash_file(saved) != file["sha256"]:
                                raise ValueError("回收区文件已改变，不能恢复")
                    moves.append((source, path))
                elif any(Path(f["path"]) == path or Path(f["path"]).is_relative_to(path) for f in manifest["files"]):
                    raise ValueError("回收区文件缺失，不能恢复")
            moved = []
            try:
                for source, path in moves:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    source.rename(path)
                    moved.append((source, path))
                for key, rows in manifest["records"].items():
                    state["collections"][key].update(deepcopy(rows))
                state["cleanup_receipts"].remove(receipt_id)
                self.store._write(state)
            except BaseException:
                for source, path in reversed(moved):
                    path.rename(source)
                raise
            return {"restored": receipt_id}
