"""Shared workflow presets, independent of execution and provider configuration."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from types import SimpleNamespace
from uuid import uuid4

import yaml

from src.config import APP_ROOT, PROJECT_ROOT


STAGES = ("separate", "asr", "align", "translate", "tts", "mix", "export")
_ALIASES = {"separation": "separate", "translation": "translate"}
_DRAFT_FIELDS = {"label", "description", "stages", "outputs", "version", "graph"}
_ITEM_FIELDS = _DRAFT_FIELDS | {"id", "revision", "builtin"}
_write_lock = threading.RLock()
_RETIRED_BUILTIN_IDS = frozenset({
    "audio_subtitles", "subtitle_translation", "subtitle_speech", "audio_translation_speech",
    "asmr_bilingual", "asr_only", "graph_audio_subtitles", "graph_subtitle_translation",
    "graph_subtitle_speech", "graph_audio_translation_speech",
})


class PresetConflictError(ValueError):
    """A preset changed since the editor loaded it, or another writer is active."""


class BuiltinPresetError(ValueError):
    """Built-in definitions can be copied or indexed, but never edited in place."""


@dataclass
class _Catalog:
    definitions: list[dict[str, Any]]
    index: dict[str, dict[str, Any]]
    original: bytes | None
    storage_version: int | None
    stored_customs: list[dict[str, Any]]
    loaded_customs: dict[str, dict[str, Any]]
    promoted_ids: set[str]
    retired_index: dict[str, dict[str, Any]]

    def item(self, preset_id: str) -> dict[str, Any]:
        definition = next((item for item in self.definitions if item["id"] == preset_id), None)
        if definition is None:
            raise KeyError("Preset does not exist")
        entry = self.index[preset_id]
        return {**deepcopy(definition), "revision": entry["revision"],
                "label": entry.get("label", definition["label"])}

    def items(self, *, active: bool) -> list[dict[str, Any]]:
        return [self.item(item["id"]) for item in self.definitions
                if self.index[item["id"]]["active"] is active]


def _text(value: Any, name: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{name} must be {'non-empty ' if required else ''}text (max {limit})")
    return value.strip()


def _stages(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(s, str) for s in value):
        raise ValueError(f"{name} must contain at least one stage")
    normalized = [_ALIASES.get(s, s) for s in value]
    if any(s not in STAGES for s in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} contains unknown or duplicate stages")
    return [s for s in STAGES if s in normalized]


def _draft(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - _DRAFT_FIELDS:
        raise ValueError("Presets accept only label, description, stages and outputs")
    if "graph" in value or value.get("version") == 2:
        if set(value) - {"version", "label", "description", "graph"} or type(value.get("version")) is not int or value["version"] != 2:
            raise ValueError("Graph presets require version 2 and cannot also contain stages or outputs")
        from src.core.orchestration.pipeline.graph_validation import validate_graph
        return {
            "version": 2,
            "label": _text(value.get("label"), "label", 100),
            "description": _text(value.get("description", ""), "description", 1000, required=False),
            "graph": validate_graph(value.get("graph"), template=True),
        }
    if "version" in value:
        raise ValueError("Legacy presets do not contain a graph version")
    stages = _stages(value.get("stages"), "stages")
    outputs = _stages(value.get("outputs"), "outputs")
    if not set(outputs) <= set(stages):
        raise ValueError("Every output must belong to a selected stage")
    return {
        "label": _text(value.get("label"), "label", 100),
        "description": _text(value.get("description", ""), "description", 1000, required=False),
        "stages": stages,
        "outputs": outputs,
    }


def _item(value: Any, *, builtin: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() - _ITEM_FIELDS:
        raise ValueError("Preset catalog contains unsupported fields")
    preset_id = value.get("id")
    if not isinstance(preset_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", preset_id):
        raise ValueError("Preset catalog contains an invalid ID")
    revision = value.get("revision", 1)
    if type(revision) is not int or revision < 1:
        raise ValueError("Preset revision must be a positive integer")
    if "builtin" in value and value["builtin"] is not builtin:
        raise ValueError("Preset catalog contains an invalid builtin flag")
    draft = {key: value[key] for key in _DRAFT_FIELDS if key in value}
    # Older shipped catalogs did not record outputs. Preserve their selections
    # explicitly; never enable a stage or infer material bindings.
    if builtin and "graph" not in draft and "outputs" not in draft:
        draft["outputs"] = draft.get("stages")
    validated = _draft(draft)
    if builtin and "graph" in draft:
        # Validate the shipped snapshot without normalizing away its explicit
        # null fields or rewriting any node, edge or output selection.
        validated["graph"] = deepcopy(draft["graph"])
    return {"id": preset_id, **validated, "revision": revision, "builtin": builtin}


def _promotion_value(value: dict[str, Any]) -> dict[str, Any]:
    """Compare original payloads, allowing only API-added optional nulls."""
    result = deepcopy(value)
    result.pop("builtin", None)
    graph = result.get("graph")
    if isinstance(graph, dict):
        for slot in graph.get("input_slots", []):
            slot.setdefault("language", None)
        for output in graph.get("outputs", []):
            output.setdefault("label", None)
    return result


@contextmanager
def _file_lock(path: Path):
    """Serialize optimistic read/replace across local backend processes too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            def lock():
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock():
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def lock():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def unlock():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        try:
            lock()
        except OSError as exc:
            raise PresetConflictError("Another preset save is in progress; reload and retry") from exc
        try:
            yield
        finally:
            handle.seek(0)
            unlock()


class PresetCatalogService:
    """Portable definitions plus a revisioned, recoverable active preset index."""

    def __init__(
        self, presets_path: Path | str | None = None, user_presets_path: Path | str | None = None,
    ) -> None:
        self._presets_path = (
            Path(presets_path) if presets_path is not None else APP_ROOT / "config" / "presets.yaml"
        )
        self._user_presets_path = (
            Path(user_presets_path) if user_presets_path is not None
            else (self._presets_path.parent if presets_path is not None else PROJECT_ROOT / "config")
            / "voice_lab" / "flow_presets.json"
        )

    def _read_builtins(self) -> list[dict[str, Any]]:
        if not self._presets_path.exists():
            return []
        try:
            with self._presets_path.open(encoding="utf-8") as file:
                data = yaml.safe_load(file)
        except (ValueError, yaml.YAMLError) as exc:
            raise ValueError("Preset catalog is unreadable; existing contents were not changed") from exc
        if (not isinstance(data, dict) or set(data) != {"presets"}
                or not isinstance(data["presets"], list)):
            raise ValueError("Preset catalog has an invalid format; existing contents were not changed")
        return [_item(value, builtin=True) for value in data["presets"]]

    def _load_catalog(self) -> _Catalog:
        definitions = self._read_builtins()
        builtins = {preset["id"]: preset for preset in definitions}
        if len(builtins) != len(definitions):
            raise ValueError("Preset catalog contains duplicate IDs")
        path = self._user_presets_path
        original = path.read_bytes() if path.exists() else None
        data, version = {}, None
        stored_customs, loaded_customs, promoted_ids = [], {}, set()
        if original is not None:
            try:
                data = json.loads(original)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Preset catalog is unreadable; existing contents were not changed") from exc
            version = data.get("version") if isinstance(data, dict) else None
            allowed = {"version", "presets", "index"} if version == 3 else {"version", "presets"}
            if (not isinstance(data, dict) or set(data) != allowed
                    or type(version) is not int or version not in (1, 2, 3)
                    or not isinstance(data.get("presets"), list)):
                raise ValueError("Preset catalog has an invalid format; existing contents were not changed")
            stored_customs = deepcopy(data["presets"])
            for raw in stored_customs:
                custom = _item(raw, builtin=False)
                preset_id = custom["id"]
                if preset_id in loaded_customs:
                    raise ValueError("Preset catalog contains duplicate IDs")
                loaded_customs[preset_id] = custom
                builtin = builtins.get(preset_id)
                if builtin is None:
                    definitions.append(custom)
                elif _promotion_value(raw) == _promotion_value(builtin):
                    # Read-only overlay. Keep the original stored custom record
                    # even on a later unrelated explicit save.
                    promoted_ids.add(preset_id)
                else:
                    raise PresetConflictError(
                        f"Preset {preset_id} differs from the new built-in snapshot; "
                        "the custom definition was preserved. Resolve the conflict before saving."
                    )
        ids = [preset["id"] for preset in definitions]
        if len(set(ids)) != len(ids):
            raise ValueError("Preset catalog contains duplicate IDs")
        index = {preset["id"]: {"active": True,
                                "revision": preset["revision"]} for preset in definitions}
        retired_index = {}
        if version == 3:
            saved = data["index"]
            if not isinstance(saved, dict) or set(saved) - set(ids) - _RETIRED_BUILTIN_IDS:
                raise ValueError("Preset index contains unknown definitions or has an invalid format")
            if set(loaded_customs) - set(saved):
                raise ValueError("Preset index is missing a custom definition; existing contents were not changed")
            for preset_id, entry in saved.items():
                if (not isinstance(entry, dict) or not {"active", "revision"} <= set(entry)
                        or set(entry) - {"active", "revision", "label"}
                        or type(entry.get("active")) is not bool
                        or type(entry.get("revision")) is not int
                        or entry["revision"] < index.get(preset_id, {}).get("revision", 1)):
                    raise ValueError("Preset index entry has an invalid format or revision")
                if "label" in entry:
                    _text(entry["label"], "label", 100)
                if preset_id not in index:
                    # These IDs remain readable only for old index compatibility;
                    # their definitions are gone and cannot appear in restore.
                    retired_index[preset_id] = deepcopy(entry)
                    continue
                index[preset_id] = deepcopy(entry)
                if "label" in entry:
                    index[preset_id]["label"] = _text(entry["label"], "label", 100)
        return _Catalog(definitions, index, original, version, stored_customs,
                        loaded_customs, promoted_ids, retired_index)

    def list_presets(self) -> list[dict[str, Any]]:
        """Read active entries without creating an index, lock file or backup."""
        return self._load_catalog().items(active=True)

    def list_archived_presets(self) -> list[dict[str, Any]]:
        return self._load_catalog().items(active=False)

    def graph_draft(self, preset_id: str) -> dict[str, Any]:
        """Read-only, explicit conversion; stage order never implies wiring."""
        from copy import deepcopy
        from src.core.orchestration.pipeline.graph_legacy import legacy_preset_to_graph

        source = next((item for item in self.list_presets() if item["id"] == preset_id), None)
        if source is None:
            raise KeyError("Preset does not exist")
        if source.get("version") == 2:
            return {"source": deepcopy(source), "graph": deepcopy(source["graph"]), "warnings": []}
        return {
            "source": deepcopy(source), "graph": legacy_preset_to_graph(source),
            "warnings": ["旧预设未保存节点连线。每个输入已保留为独立素材槽，请确认连线、语言和参数后另存；原预设不变。"],
        }

    def _backup_original(self, original: bytes, reason: str) -> None:
        """Verify the exact pre-write bytes; never scan or delete older backups."""
        digest = hashlib.sha256(original).hexdigest()
        path = self._user_presets_path
        backup = path.with_name(f"{path.name}.{reason}.{digest}.bak")
        if not backup.exists():
            try:
                with backup.open("xb") as file:
                    file.write(original)
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError:
                pass
        saved = backup.read_bytes()
        if saved != original or hashlib.sha256(saved).hexdigest() != digest:
            raise OSError("Preset backup verification failed; original catalog was not replaced")

    def _write(self, catalog: _Catalog) -> None:
        path = self._user_presets_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if catalog.storage_version in (1, 2) and catalog.original is not None:
            self._backup_original(catalog.original, "pre-v3")
        elif catalog.original is not None and (catalog.promoted_ids or catalog.retired_index):
            self._backup_original(catalog.original, "pre-builtin-catalog")
        remaining = {item["id"]: item for item in catalog.definitions if not item["builtin"]}
        customs = []
        for raw in catalog.stored_customs:
            preset_id = raw["id"]
            if preset_id in catalog.promoted_ids:
                customs.append(raw)
            elif preset_id in remaining:
                current = remaining.pop(preset_id)
                customs.append(raw if current == catalog.loaded_customs[preset_id] else current)
        customs.extend(remaining.values())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump({"version": 3,
                           "presets": customs,
                           "index": {**catalog.retired_index, **catalog.index}}, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            current = path.read_bytes() if path.exists() else None
            if current != catalog.original:
                raise PresetConflictError("Preset catalog changed while saving; reload before retrying")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _speech_connection_references(catalog: _Catalog, connection_ref: str, recipe_ids: set[str]) -> dict:
        references = []
        for definition in catalog.definitions:
            item = catalog.item(definition["id"])
            for node in item.get("graph", {}).get("nodes", []):
                if node["kind"] != "tts":
                    continue
                options = node["options"]
                source = options.get("speech_source")
                recipe_id = options.get("speech_recipe_id")
                kinds = []
                if isinstance(source, dict) and source.get("connection_ref") == connection_ref:
                    kinds.append("inline")
                if isinstance(recipe_id, str) and recipe_id in recipe_ids:
                    kinds.append("recipe")
                # A template may still be an unconfigured draft. Check both
                # references independently, and never crash on portable but
                # incomplete source data in an unrelated template.
                for kind in kinds:
                    references.append({"preset_id": item["id"], "label": item["label"],
                                       "revision": item["revision"], "builtin": item["builtin"],
                                       "active": catalog.index[item["id"]]["active"],
                                       "node_id": node["id"], "kind": kind,
                                       **({"recipe_id": recipe_id} if kind == "recipe" else {})})
        # Include the complete catalog state: a new reference after preview must
        # invalidate deletion even if the formerly affected items are unchanged.
        guard = {"original": hashlib.sha256(catalog.original or b"").hexdigest(),
                 "definitions": catalog.definitions, "index": catalog.index,
                 "connection_ref": connection_ref, "recipe_ids": sorted(recipe_ids)}
        token = hashlib.sha256(json.dumps(guard, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {"token": token, "references": references}

    def speech_connection_references(self, connection_ref: str, recipe_ids: list[str]) -> dict:
        """Read-only impact list, including archived custom and builtin graphs."""
        with _write_lock:
            return self._speech_connection_references(self._load_catalog(), connection_ref, set(recipe_ids))

    @contextmanager
    def speech_connection_migration(self, connection_ref: str, recipe_ids: list[str], expected_token: str):
        """Hold catalog before speech-store locks; never rewrite submitted graphs.

        The caller first creates immutable replacement recipe revisions while
        retaining the connection, then applies this migration, and only finally
        deletes the connection. A failure therefore leaves the old connection
        available. Detach skips apply and deliberately leaves missing references.
        """
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            impact = self._speech_connection_references(catalog, connection_ref, set(recipe_ids))
            if impact["token"] != expected_token:
                raise PresetConflictError("Workflow references changed; reload the deletion preview")
            applied = False

            def apply(recipe_id_map: dict[str, str], replacement_ref: str) -> list[dict]:
                nonlocal applied
                if applied:
                    raise PresetConflictError("Connection migration has already been applied")
                if not replacement_ref or replacement_ref == connection_ref:
                    raise ValueError("Choose a different replacement connection")
                refs = impact["references"]
                if any(ref["builtin"] for ref in refs):
                    raise BuiltinPresetError("Built-in workflows cannot be silently changed; copy and edit them first")
                if any(ref["kind"] == "recipe" and ref["recipe_id"] not in recipe_id_map for ref in refs):
                    raise PresetConflictError("A workflow uses a historical recipe revision; explicitly update it first")
                changed = []
                for preset_id in dict.fromkeys(ref["preset_id"] for ref in refs):
                    item = catalog.item(preset_id)
                    for ref in (ref for ref in refs if ref["preset_id"] == preset_id):
                        node = next(node for node in item["graph"]["nodes"] if node["id"] == ref["node_id"])
                        if ref["kind"] == "inline":
                            node["options"]["speech_source"]["connection_ref"] = replacement_ref
                        else:
                            node["options"]["speech_recipe_id"] = recipe_id_map[ref["recipe_id"]]
                    value = _draft({key: item[key] for key in _DRAFT_FIELDS if key in item})
                    revised = {"id": preset_id, **value, "revision": item["revision"] + 1, "builtin": False}
                    catalog.definitions = [revised if entry["id"] == preset_id else entry for entry in catalog.definitions]
                    catalog.index[preset_id] = {**catalog.index[preset_id], "revision": revised["revision"]}
                    changed.append({"id": preset_id, "label": item["label"], "revision": revised["revision"]})
                if changed:
                    if catalog.original is not None:
                        self._backup_original(catalog.original, "pre-connection-replacement")
                    self._write(catalog)
                applied = True
                return changed

            yield SimpleNamespace(references=impact["references"], apply=apply)

    def create_preset(self, draft: dict[str, Any]) -> dict[str, Any]:
        value = _draft(draft)
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            item = {"id": f"custom_{uuid4().hex}", **value, "revision": 1, "builtin": False}
            catalog.definitions.append(item)
            catalog.index[item["id"]] = {"active": True, "revision": 1}
            self._write(catalog)
            return item

    def copy_preset(self, preset_id: str, label: str) -> dict[str, Any]:
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            source = catalog.item(preset_id)
            if not catalog.index[preset_id]["active"]:
                raise KeyError("Preset does not exist")
            value = _draft({**{key: source[key] for key in _DRAFT_FIELDS if key in source}, "label": label})
            item = {"id": f"custom_{uuid4().hex}", **value, "revision": 1, "builtin": False}
            catalog.definitions.append(item)
            catalog.index[item["id"]] = {"active": True, "revision": 1}
            self._write(catalog)
            return item

    def update_preset(self, preset_id: str, draft: dict[str, Any], revision: int) -> dict[str, Any]:
        value = _draft(draft)
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            current = catalog.item(preset_id)
            if current["builtin"]:
                raise BuiltinPresetError("Built-in presets are read-only; copy to a custom preset first")
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before saving")
            if not catalog.index[preset_id]["active"]:
                raise PresetConflictError("Preset is archived; restore it before editing")
            item = {"id": preset_id, **value, "revision": revision + 1, "builtin": False}
            catalog.definitions = [
                item if preset["id"] == preset_id else preset
                for preset in catalog.definitions
            ]
            catalog.index[preset_id] = {"active": True, "revision": revision + 1}
            self._write(catalog)
            return item

    def delete_preset(self, preset_id: str, revision: int) -> None:
        """Remove only index visibility; keep both custom and builtin definitions."""
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            current = catalog.item(preset_id)
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before deleting")
            entry = catalog.index[preset_id]
            if not entry["active"]:
                raise PresetConflictError("Preset is already archived; reload the archived list")
            entry.update(active=False, revision=revision + 1)
            self._write(catalog)

    def permanently_delete_preset(self, preset_id: str, revision: int) -> dict[str, str]:
        """Delete one custom definition and index entry; submitted snapshots are independent."""
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            try:
                current = catalog.item(preset_id)
            except KeyError:
                return {"id": preset_id, "status": "already_missing"}
            if current["builtin"]:
                raise BuiltinPresetError("Built-in presets cannot be permanently deleted; remove from the active catalog instead")
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before permanently deleting")
            catalog.definitions = [item for item in catalog.definitions if item["id"] != preset_id]
            del catalog.index[preset_id]
            self._write(catalog)
            return {"id": preset_id, "status": "deleted"}

    def restore_preset(self, preset_id: str, revision: int, label: str | None = None) -> dict[str, Any]:
        """Explicitly restore one ID; a name conflict never replaces another entry."""
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        if label is not None:
            label = _text(label, "label", 100)
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            catalog = self._load_catalog()
            current = catalog.item(preset_id)
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before restoring")
            entry = catalog.index[preset_id]
            if entry["active"]:
                raise PresetConflictError("Preset is already active; reload the preset list")
            restored_label = current["label"] if label is None else label
            if any(item["label"].strip().casefold() == restored_label.strip().casefold()
                   for item in catalog.items(active=True)):
                raise PresetConflictError("An active preset already uses this name; choose another name before restoring")
            entry.update(active=True, revision=revision + 1, label=restored_label)
            self._write(catalog)
            return catalog.item(preset_id)


_service: PresetCatalogService | None = None
_lock = threading.Lock()


def get_preset_catalog_service() -> PresetCatalogService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PresetCatalogService()
    return _service
