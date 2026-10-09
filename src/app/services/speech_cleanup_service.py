"""Confirmed deletion of VoiceLab-owned data, retaining active/reference guards.

Legacy quarantine data is read-only unless the user selects that exact item and
confirms deletion. New deletions never create archives or recoverable copies.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

from src.core.speech.store import reference_file_guard, _hash_file


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


def without_frozen_recipes(value):
    """Read dependencies without treating a complete value snapshot as an ID link."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, (list, tuple)):
        return [without_frozen_recipes(item) for item in value]
    if not isinstance(value, dict):
        return value
    snapshot = next((value[key] for key in ("recipe_snapshot", "recipe")
                     if isinstance(value.get(key), dict) and all(field in value[key]
                     for field in ("id", "provider_id", "model", "mode", "variant"))
                     and value.get("recipe_id", value[key]["id"]) == value[key]["id"]), None)
    omitted = {"recipe_snapshot", "recipe", "recipe_id", "voice_id"} if snapshot else set()
    result = {key: without_frozen_recipes(item) for key, item in value.items() if key not in omitted}
    request = value.get("compiled_request")
    # Completed takes can be read, assembled and saved as a new recipe from the
    # frozen value. Only this matching compiler provenance is not a live link;
    # unknown/nested references and mismatched requests remain blockers.
    if (snapshot and isinstance(request, dict) and request.get("recipe_id") == snapshot["id"]
            and all(request.get(key) == snapshot[key] for key in ("provider_id", "model", "mode"))):
        result["compiled_request"].pop("recipe_id", None)
    return result


def connection_receipt_dependencies(receipts):
    """Project only proven completed mappings as provenance; never change storage.

    Completed connection deletion replays its saved result without dereferencing
    recipes. Prepared, malformed and future receipt formats remain dependencies.
    All fields outside the four known mapping locations still undergo scanning.
    """
    if not isinstance(receipts, dict):
        return receipts
    projected = dict(receipts)
    fields = {"request_token", "connection_id", "provider_id", "action", "replacement_ref",
              "catalog_token", "catalog_references", "recipe_ids", "recipe_revisions",
              "recipe_id_map", "guard_token", "state", "result"}
    for token, receipt in receipts.items():
        if not isinstance(receipt, dict) or set(receipt) != fields:
            continue
        if (receipt["state"] != "completed" or receipt["action"] != "replace"
                or receipt["request_token"] != token
                or any(not isinstance(receipt[key], str) or not receipt[key] for key in
                       ("request_token", "connection_id", "provider_id", "replacement_ref", "catalog_token", "guard_token"))
                or receipt["connection_id"] == receipt["replacement_ref"]):
            continue
        ids, revisions, result = receipt["recipe_ids"], receipt["recipe_revisions"], receipt["result"]
        if (not isinstance(ids, list) or any(not isinstance(id, str) or not id for id in ids)
                or len(set(ids)) != len(ids) or not isinstance(revisions, list)
                or not isinstance(receipt["recipe_id_map"], dict)
                or not isinstance(receipt["catalog_references"], list)
                or not isinstance(result, dict)
                or set(result) != {"deleted_connection_id", "action", "recipe_revisions", "defaults"}
                or result["deleted_connection_id"] != receipt["connection_id"]
                or result["action"] != receipt["action"]
                or result["recipe_revisions"] != revisions or not isinstance(result["defaults"], list)):
            continue
        if (any(not isinstance(row, dict) for row in receipt["catalog_references"])
                or any(not isinstance(row, dict) or set(row) != {"provider_id", "connection_ref", "revision"}
                       or not isinstance(row["provider_id"], str) or not row["provider_id"]
                       or not (row["connection_ref"] is None or isinstance(row["connection_ref"], str) and row["connection_ref"])
                       or type(row["revision"]) is not int or row["revision"] < 1
                       for row in result["defaults"])):
            continue
        if any(not isinstance(row, dict) or set(row) != {"previous_id", "id", "revision"}
               or row["previous_id"] not in ids or not isinstance(row["id"], str) or not row["id"]
               or row["id"] in ids or type(row["revision"]) is not int or row["revision"] < 2
               for row in revisions):
            continue
        mapping = {row["previous_id"]: row["id"] for row in revisions}
        if (mapping != receipt["recipe_id_map"] or len(mapping) != len(revisions)
                or len(set(mapping.values())) != len(revisions)):
            continue
        projected[token] = {key: value for key, value in receipt.items()
                            if key not in {"recipe_ids", "recipe_revisions", "recipe_id_map"}}
        projected[token]["result"] = {key: value for key, value in result.items() if key != "recipe_revisions"}
    return projected


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
                # Old files never move, restore or purge merely because a route
                # is read. Legacy entries require their own explicit confirmation.
                yield

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
        result["legacy_data"] = [json.loads(owned_path(self.store.root, path).read_text(encoding="utf-8"))
            for path in (self.store.root / "_trash").glob("*/manifest.json")]
        return result

    def preview(self, kind, item_id="all"):
        with self.guard():
            return self._preview(kind, item_id)[0]

    def _preview(self, kind, item_id):
        if kind == "legacy-trash":
            return self._legacy_deletion_preview(item_id)
        state = self.store._read()
        records = state["collections"]
        selected = {key: {} for key in records}
        history_updates = {}
        paths, blockers = [], []
        external = self.external()
        if any(batch.state not in {"completed", "completed_with_errors", "cancelled", "interrupted", "history_deleted"}
               for batch in external.get("batches", [])):
            blockers.append("存在未结束批任务，请先结束批任务")
        # Built-in initialization markers prevent deleted defaults from reappearing;
        # they do not own the user's recipe and must remain after a true deletion.
        external["store_metadata"] = {key: value for key, value in state.items() if key not in {"collections", "builtin_recipes"}}
        if kind == "recipes" and "connection_deletions" in external["store_metadata"]:
            external["store_metadata"]["connection_deletions"] = connection_receipt_dependencies(state["connection_deletions"])
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
            # Current product policy permits deleting active or legacy-archived
            # rules after the same reference/active-task checks and confirmation.
            selected[kind] = {id: row for id, row in records[kind].items()
                              if self.store._recipe_root(records[kind], id) == root}
            if root in records["rule_states"]:
                selected["rule_states"][root] = records["rule_states"][root]
            for voice_id in {row.get("voice_id") for row in selected[kind].values()} - {None}:
                others = {key: {id: row for id, row in rows.items() if id not in selected[key]}
                          for key, rows in records.items() if key != "voices"}
                if voice_id in records["voices"] and not references([others, external], {voice_id}, []):
                    selected["voices"][voice_id] = records["voices"][voice_id]
        elif kind == "assets":
            asset = records[kind][item_id]
            selected[kind][item_id] = asset
            # Archival is not a prerequisite for an explicitly confirmed delete.
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
        if kind == "recipes":
            for id, take in remaining["takes"].items():
                recipe = selected["recipes"].get(take.get("recipe_id"))
                if recipe and not take.get("recipe_snapshot") and all(field in recipe for field in ("provider_id", "model", "mode", "variant")):
                    # Freeze the exact immutable source used by old ID-only takes;
                    # their execution data/audio and original IDs remain unchanged.
                    history_updates[id] = {**deepcopy(take), "recipe_snapshot": deepcopy(recipe)}
            remaining["takes"] = {**remaining["takes"], **history_updates}
            remaining = without_frozen_recipes(remaining)
            external = without_frozen_recipes(external)
            for voice_id in {row.get("voice_id") for row in selected["recipes"].values()} - {None}:
                others = {key: value for key, value in remaining.items() if key != "voices"}
                if voice_id in records["voices"] and not references([others, external], {voice_id}, []):
                    selected["voices"][voice_id] = records["voices"][voice_id]
                    remaining["voices"].pop(voice_id, None)
                    ids.add(voice_id)
        for key, value in {**remaining, **external}.items():
            if references(value, ids, paths):
                label = {"voices": "保存声音", "recipes": "音色规则", "experiments": "试音实验", "takes": "候选音频",
                         "selections": "采用记录", "assemblies": "组装记录", "assets": "参考录音", "plans": "台词",
                         "tasks": "任务历史", "artifacts": "任务产物", "workflows": "工作流", "batches": "批任务",
                         "legacy_data": "旧版遗留数据", "staged_references": "录音暂存",
                         "persistent_history": "持久任务和恢复记录"}.get(key, "其他保存数据")
                matches = [str(id) for id, row in value.items() if references(row, ids, paths)] if isinstance(value, dict) else []
                blockers.append(f"仍被{label}{'（' + '、'.join(matches[:4]) + '）' if matches else ''}引用；请先处理这些引用")
        files = file_manifest(self.store.root, paths)
        payload = {"kind": kind, "item_id": item_id, "records": selected, "history_updates": history_updates,
                   "paths": [str(p) for p in paths], "files": files, "blockers": sorted(set(blockers))}
        token = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"kind": kind, "item_id": item_id, "token": token, "blockers": payload["blockers"],
                "records": {k: len(v) for k, v in selected.items() if v}, "files": files,
                "bytes": sum(f["bytes"] for f in files), "paths": payload["paths"],
                "recoverable": False}, payload

    def execute(self, kind, item_id, token, confirmed=False):
        if confirmed is not True:
            raise ValueError("请预览影响并确认本次清理")
        with self.guard():
            preview, payload = self._preview(kind, item_id)
            if preview["token"] != token:
                raise ValueError("内容或引用已改变，请重新预览")
            if preview["blockers"]:
                raise ValueError("；".join(preview["blockers"]))
            if kind == "legacy-trash":
                return self._delete_legacy(item_id, payload)
            if not preview["paths"] and not preview["records"]:
                raise ValueError("没有可清理的无引用内容")
            # All existing task, worker, reference, path and stale-preview guards
            # above remain mandatory. Delete only the reviewed owned file manifest.
            # Keep records until filesystem deletion succeeds, so a partial failure
            # stays visible and can be explicitly retried; never make recovery copies.
            self._delete_reviewed_files(payload["paths"], payload["files"])
            state = self.store._read()
            state["collections"]["takes"].update(payload.get("history_updates", {}))
            for key, rows in payload["records"].items():
                for id in rows:
                    del state["collections"][key][id]
            try:
                self.store._write(state)
            except OSError as exc:
                raise ValueError("自有文件已删除，但记录保存失败；请刷新后重试删除记录") from exc
            return {"deleted": item_id, "kind": kind, "recoverable": False,
                    "files_deleted": len(payload["files"]), "bytes_deleted": preview["bytes"]}

    def _delete_reviewed_files(self, paths, files):
        if file_manifest(self.store.root, [Path(path) for path in paths]) != files:
            raise ValueError("文件已改变，请重新确认删除")
        for file in files:
            path = owned_path(self.store.root, file["path"])
            if _hash_file(path) != file["sha256"]:
                raise ValueError("文件已改变，请重新确认删除")
            path.unlink()
        # Never recursively remove new/unreviewed files added to a directory.
        for raw in paths:
            path = owned_path(self.store.root, raw)
            if path.is_dir():
                for folder in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                    owned_path(self.store.root, folder).rmdir()
                path.rmdir()

    def legacy_records(self):
        with self.guard():
            return [{"id": path.parent.name, "directory": str(path.parent),
                     **{key: value for key, value in json.loads(owned_path(self.store.root, path).read_text(encoding="utf-8")).items()
                        if key in {"kind", "item_id", "created_at"}}}
                    for path in (self.store.root / "_trash").glob("*/manifest.json")]

    def _legacy_deletion_preview(self, receipt_id):
        if not re.fullmatch(r"[0-9a-f]{32}", receipt_id):
            raise ValueError("无效回收记录")
        state = self.store._read()
        trash = owned_path(self.store.root, self.store.root / "_trash" / receipt_id)
        manifest = json.loads((trash / "manifest.json").read_text(encoding="utf-8"))
        ids = {id for rows in manifest["records"].values() for id in rows}
        paths = [owned_path(self.store.root, value) for value in manifest["paths"]]
        evidence = self.external()
        evidence["legacy_data"] = [item for item in evidence["legacy_data"] if item["id"] != receipt_id]
        evidence["speech"] = state["collections"]
        blockers = [f"{key}仍有引用，保留回收内容" for key, value in evidence.items() if references(value, ids, paths)]
        if any(status.state not in {"completed", "failed", "cancelled", "skipped"}
               or self.speech.dispatcher.has_live_worker(status.task_id) for _, status in evidence["tasks"]):
            blockers.append("存在未结束任务或尚未退出的工作线程")
        if any(batch.state not in {"completed", "completed_with_errors", "cancelled", "interrupted", "history_deleted"}
               for batch in evidence.get("batches", [])):
            blockers.append("存在未结束批任务")
        files = file_manifest(self.store.root, [trash])
        payload = {"kind": "legacy-trash", "item_id": receipt_id, "blockers": blockers, "files": files,
                   "records": {}, "paths": [str(trash)], "bytes": sum(file["bytes"] for file in files), "recoverable": False}
        payload["token"] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return payload, manifest

    def _delete_legacy(self, receipt_id, manifest):
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
        state["cleanup_receipts"] = [id for id in state.get("cleanup_receipts", []) if id != receipt_id]
        self.store._write(state)
        (trash / "manifest.json").unlink()
        trash.rmdir()
        return {"purged": receipt_id, "recoverable": False}
