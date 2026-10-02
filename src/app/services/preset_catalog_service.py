"""Shared workflow presets, independent of execution and provider configuration."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from uuid import uuid4

import yaml

from src.config import PROJECT_ROOT


STAGES = ("separate", "asr", "align", "translate", "tts", "mix", "export")
_ALIASES = {"separation": "separate", "translation": "translate"}
_DRAFT_FIELDS = {"label", "description", "stages", "outputs", "version", "graph"}
_ITEM_FIELDS = _DRAFT_FIELDS | {"id", "revision", "builtin"}
_write_lock = threading.RLock()


class PresetConflictError(ValueError):
    """A preset changed since the editor loaded it, or another writer is active."""


class BuiltinPresetError(ValueError):
    """Built-ins can be copied, but never edited or deleted in place."""


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
    return {"id": preset_id, **_draft(draft), "revision": revision, "builtin": builtin}


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
    """One catalog for settings and workbench, with revision-checked custom saves."""

    def __init__(
        self, presets_path: Path | str | None = None, user_presets_path: Path | str | None = None,
    ) -> None:
        self._presets_path = (
            Path(presets_path) if presets_path is not None else PROJECT_ROOT / "config" / "presets.yaml"
        )
        self._user_presets_path = (
            Path(user_presets_path) if user_presets_path is not None
            else self._presets_path.parent / "voice_lab" / "flow_presets.json"
        )

    def _read(self, *, builtin: bool) -> list[dict[str, Any]]:
        path = self._presets_path if builtin else self._user_presets_path
        if not path.exists():
            return []
        try:
            with path.open(encoding="utf-8") as file:
                data = yaml.safe_load(file) if builtin else json.load(file)
        except (ValueError, yaml.YAMLError) as exc:
            raise ValueError("Preset catalog is unreadable; existing contents were not changed") from exc
        allowed_keys = {"presets"} if builtin else {"version", "presets"}
        if (not isinstance(data, dict) or data.keys() - allowed_keys
                or not isinstance(data.get("presets"), list)
                or (not builtin and (type(data.get("version")) is not int or data["version"] not in (1, 2)))):
            raise ValueError("Preset catalog has an invalid format; existing contents were not changed")
        return [_item(value, builtin=builtin) for value in data["presets"]]

    def list_presets(self) -> list[dict[str, Any]]:
        presets = self._read(builtin=True) + self._read(builtin=False)
        ids = [preset["id"] for preset in presets]
        if len(set(ids)) != len(ids):
            raise ValueError("Preset catalog contains duplicate IDs")
        return presets

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

    def _write(self, presets: list[dict[str, Any]]) -> None:
        path = self._user_presets_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump({"version": 2 if any("graph" in item for item in presets) else 1, "presets": presets}, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def create_preset(self, draft: dict[str, Any]) -> dict[str, Any]:
        value = _draft(draft)
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            presets = self.list_presets()
            item = {"id": f"custom_{uuid4().hex}", **value, "revision": 1, "builtin": False}
            self._write([preset for preset in presets if not preset["builtin"]] + [item])
            return item

    def copy_preset(self, preset_id: str, label: str) -> dict[str, Any]:
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            presets = self.list_presets()
            source = next((preset for preset in presets if preset["id"] == preset_id), None)
            if source is None:
                raise KeyError("Preset does not exist")
            value = _draft({**{key: source[key] for key in _DRAFT_FIELDS if key in source}, "label": label})
            item = {"id": f"custom_{uuid4().hex}", **value, "revision": 1, "builtin": False}
            self._write([preset for preset in presets if not preset["builtin"]] + [item])
            return item

    def update_preset(self, preset_id: str, draft: dict[str, Any], revision: int) -> dict[str, Any]:
        value = _draft(draft)
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            presets = self.list_presets()
            current = next((preset for preset in presets if preset["id"] == preset_id), None)
            if current is None:
                raise KeyError("Preset does not exist")
            if current["builtin"]:
                raise BuiltinPresetError("Built-in presets are read-only; copy to a custom preset first")
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before saving")
            item = {"id": preset_id, **value, "revision": revision + 1, "builtin": False}
            self._write([
                item if preset["id"] == preset_id else preset
                for preset in presets if not preset["builtin"]
            ])
            return item

    def delete_preset(self, preset_id: str, revision: int) -> None:
        """Delete one custom preset only if the caller still owns its revision."""
        if type(revision) is not int or revision < 1:
            raise ValueError("Preset revision must be a positive integer")
        with _write_lock, _file_lock(self._user_presets_path.with_suffix(".json.lock")):
            presets = self.list_presets()
            current = next((preset for preset in presets if preset["id"] == preset_id), None)
            if current is None:
                raise KeyError("Preset does not exist")
            if current["builtin"]:
                raise BuiltinPresetError("Built-in presets are read-only and cannot be deleted")
            if current["revision"] != revision:
                raise PresetConflictError("Preset changed since it was loaded; reload before deleting")
            self._write([
                preset for preset in presets
                if not preset["builtin"] and preset["id"] != preset_id
            ])


_service: PresetCatalogService | None = None
_lock = threading.Lock()


def get_preset_catalog_service() -> PresetCatalogService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PresetCatalogService()
    return _service
