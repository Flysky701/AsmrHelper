"""Durable, provider-neutral speech records and owned reference audio.

The store never uploads audio or removes a user's source file. Immutable
records are revised by creating another record, so submitted work stays fixed.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any
from uuid import uuid4


COLLECTIONS = frozenset({"voices", "recipes", "experiments", "takes", "selections", "assemblies", "assets", "plans", "connections", "imports", "rule_states", "fish_clones"})
IMMUTABLE = frozenset({"recipes", "takes", "plans", "assets", "assemblies"})
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_REFERENCE_FILE_LOCK = threading.RLock()
_SECRET_KEYS = {"api_key", "apikey", "authorization", "access_token", "secret", "password", "credential"}


class ConnectionConflictError(ValueError):
    """A connection or one of its references changed after review."""


@contextmanager
def reference_file_guard():
    """Serialize reference capture with deletion until source metadata is durable."""
    with _REFERENCE_FILE_LOCK:
        yield


def _reference_file_operation(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        with reference_file_guard():
            return method(*args, **kwargs)
    return guarded


def reference_submission_operation(method):
    """Batch admission already holds its own reference lease; avoid lock inversion."""
    @wraps(method)
    def guarded(*args, **kwargs):
        if str(kwargs.get("task_source", "")).startswith("batch-run:"):
            return method(*args, **kwargs)
        with reference_file_guard():
            return method(*args, **kwargs)
    return guarded


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def companion_subtitle_paths(audio_path):
    """Recognize both recording.vtt and recording.wav.vtt sidecars."""
    if not audio_path:
        return []
    audio = Path(audio_path)
    return [candidate for suffix in (".vtt", ".srt")
            for candidate in (Path(str(audio) + suffix), audio.with_suffix(suffix)) if candidate.is_file()]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _readable_audio(source: Path, directory: Path) -> Path:
    """Decode unsupported containers to disk, keeping the exact source bytes."""
    import soundfile as sf
    try:
        with sf.SoundFile(source):
            return source
    except (OSError, RuntimeError):
        from src.utils import get_ffmpeg
        decoded = directory / "decoded.wav"
        result = subprocess.run([
            get_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", str(source),
            "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", "-rf64", "auto", str(decoded),
        ], capture_output=True, timeout=300, check=False)
        if result.returncode != 0:
            raise ValueError("Reference audio could not be decoded") from None
        with sf.SoundFile(decoded):
            return decoded


def _no_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _SECRET_KEYS:
                raise ValueError("Speech records accept credential references, not secrets")
            _no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child)


def validate_plan(text: str, proposed: dict) -> dict:
    """Validate intentions against immutable text; offsets are Python codepoints."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Plan text must not be empty")
    if not isinstance(proposed, dict):
        raise ValueError("Plan must be an object")
    if set(proposed) - {"id", "text", "text_hash", "segments", "revision", "created_at", "updated_at", "previous_id", "use_recipe_defaults"}:
        raise ValueError("Plans may contain only original text, offsets and intentions")
    if "use_recipe_defaults" in proposed and type(proposed["use_recipe_defaults"]) is not bool:
        raise ValueError("use_recipe_defaults must be a boolean")
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if proposed.get("text", text) != text or proposed.get("text_hash", text_hash) != text_hash:
        raise ValueError("A plan cannot replace the original text")
    segments = proposed.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Plan must cover the complete original text")
    cursor = 0
    normalized = []
    ids = set()
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) - {"id", "start", "end", "delivery", "emotion", "pause_ms"}:
            raise ValueError("Segments may contain only offsets and delivery intentions")
        start, end = segment.get("start"), segment.get("end")
        if type(start) is not int or type(end) is not int or start != cursor or not start < end <= len(text):
            raise ValueError("Segment offsets must cover text without gaps, overlap or additions")
        delivery, emotion = segment.get("delivery", "normal"), segment.get("emotion", "neutral")
        pause = segment.get("pause_ms", 0)
        if delivery not in {"normal", "soft", "whisper"}:
            raise ValueError("Unknown delivery intention")
        if not isinstance(emotion, str) or not emotion.strip() or len(emotion) > 100:
            raise ValueError("Emotion must be a short intention")
        if type(pause) is not int or not 0 <= pause <= 60000:
            raise ValueError("pause_ms must be an integer between 0 and 60000")
        segment_id = segment.get("id") or hashlib.sha256(f"{text_hash}:{start}:{end}".encode()).hexdigest()[:24]
        if not isinstance(segment_id, str) or not segment_id or segment_id in ids:
            raise ValueError("Segment IDs must be unique nonempty strings")
        ids.add(segment_id)
        normalized.append({"id": segment_id, "start": start, "end": end, "delivery": delivery, "emotion": emotion, "pause_ms": pause})
        cursor = end
    if cursor != len(text):
        raise ValueError("Plan dropped text")
    return {"id": str(uuid4()), "text": text, "text_hash": text_hash, "segments": normalized,
            **({"use_recipe_defaults": proposed["use_recipe_defaults"]} if "use_recipe_defaults" in proposed else {})}


def build_plan(text: str) -> dict:
    """Split at sentence punctuation while retaining every character verbatim."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Plan text must not be empty")
    boundaries = [match.end() for match in re.finditer(r"[。！？!?]+[\"'”’」』]*|\n+", text)]
    if not boundaries or boundaries[-1] != len(text):
        boundaries.append(len(text))
    start = 0
    segments = []
    for end in boundaries:
        if end > start:
            segments.append({"start": start, "end": end})
            start = end
    return validate_plan(text, {"segments": segments})


class SpeechStore:
    def __init__(self, root: Path | None = None):
        if root is None:
            from src.config import PROJECT_ROOT
            root = PROJECT_ROOT / "config" / "voice_lab"
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "store.json"
        self.assets_root = self.root / "assets"
        with _LOCKS_GUARD:
            self._thread_lock = _LOCKS.setdefault(str(self.root).casefold(), threading.RLock())

    @contextmanager
    def _locked(self, lock_name=".store.lock"):
        with self._thread_lock:
            with (self.root / lock_name).open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                if os.name == "nt":
                    import msvcrt
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Speech store is busy") from None
                            time.sleep(0.02)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _collection(collection: str) -> None:
        if collection not in COLLECTIONS:
            raise ValueError(f"Unknown speech collection: {collection}")

    def _read(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "collections": {key: {} for key in COLLECTIONS}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("collections"), dict):
            raise ValueError("Unsupported or corrupt speech store")
        for key in COLLECTIONS:
            data["collections"].setdefault(key, {})
        return data

    def _write(self, data: dict) -> None:
        self._atomic_json(self.path, data)

    @staticmethod
    def _atomic_json(path: Path, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list(self, collection: str) -> list[dict]:
        self._collection(collection)
        with self._locked():
            return deepcopy(list(self._read()["collections"][collection].values()))

    def get(self, collection: str, id: str) -> dict:
        self._collection(collection)
        with self._locked():
            try:
                return deepcopy(self._read()["collections"][collection][id])
            except KeyError:
                raise KeyError(f"Unknown {collection} record: {id}") from None

    def resolve_local_connection(self, provider_id: str, name: str) -> dict | None:
        """Create the ordinary local default once; leave ambiguous choices to the user."""
        with self._locked():
            state = self._read()
            connections = state["collections"]["connections"]
            selection = state.get("connection_defaults", {}).get(provider_id)
            if selection is not None:
                selected = connections.get(selection.get("connection_ref"))
                if selected is not None:
                    return deepcopy(selected) if selected.get("deployment") == "local" else None
                if selection.get("connection_ref") is None:
                    return {"id": "engine-default-" + provider_id, "revision": 1,
                            "name": name, "provider_id": provider_id, "deployment": "local"}
                raise ConnectionConflictError("Default connection no longer exists; select a connection again")
            candidates = [item for item in connections.values() if item.get("provider_id") == provider_id]
            if candidates:
                if len(candidates) == 1 and candidates[0].get("deployment") == "local":
                    return deepcopy(candidates[0])
                return None
            record = {"id": str(uuid4()), "revision": 1, "name": name,
                      "provider_id": provider_id, "deployment": "local", "timeout": 120,
                      "created_at": _now(), "updated_at": _now()}
            self._validate("connections", record)
            connections[record["id"]] = record
            self._write(state)
            return deepcopy(record)

    @staticmethod
    def _connection_signature(state: dict) -> str:
        records = state["collections"]
        value = {key: records[key] for key in ("connections", "recipes", "rule_states")}
        value["defaults"] = state.get("connection_defaults", {})
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _connection_summary(connection: dict, defaults: dict) -> dict:
        fields = ("id", "name", "provider_id", "deployment", "revision")
        return {**{key: connection[key] for key in fields},
                "is_default": defaults.get(connection["provider_id"], {}).get("connection_ref") == connection["id"]}

    def connection_catalog(self) -> tuple[list[dict], list[dict]]:
        with self._locked():
            state = self._read()
            defaults = state.get("connection_defaults", {})
            connections = [dict(item, is_default=defaults.get(item["provider_id"], {}).get("connection_ref") == item["id"])
                           for item in state["collections"]["connections"].values()]
            return deepcopy(connections), deepcopy(list(defaults.values()))

    def default_connection(self, provider_id: str) -> dict | None:
        with self._locked():
            state = self._read()
            ref = state.get("connection_defaults", {}).get(provider_id, {}).get("connection_ref")
            if ref is None:
                return None
            connection = state["collections"]["connections"].get(ref)
            if connection is None or connection["provider_id"] != provider_id:
                raise ConnectionConflictError("Default connection is unavailable; select a connection again")
            return deepcopy(connection)

    def set_default_connection(self, connection_id: str, expected_revision: int,
                               expected_default_revision: int) -> dict:
        with self._locked():
            state = self._read()
            connection = state["collections"]["connections"].get(connection_id)
            if connection is None:
                raise KeyError("Connection no longer exists")
            defaults = state.setdefault("connection_defaults", {})
            previous = defaults.get(connection["provider_id"], {})
            if (type(expected_revision) is not int or type(expected_default_revision) is not int
                    or connection["revision"] != expected_revision
                    or previous.get("revision", 0) != expected_default_revision):
                raise ConnectionConflictError("Connection or default changed; reload before selecting")
            defaults[connection["provider_id"]] = {"provider_id": connection["provider_id"],
                "connection_ref": connection_id, "revision": expected_default_revision + 1}
            self._write(state)
            return {"connection": self._connection_summary(connection, defaults),
                    "defaults": deepcopy(list(defaults.values()))}

    def connection_deletion_preview(self, connection_id: str) -> dict:
        with self._locked():
            state = self._read()
            records = state["collections"]
            connection = records["connections"].get(connection_id)
            if connection is None:
                raise KeyError("Connection no longer exists")
            latest = {}
            for recipe in records["recipes"].values():
                root = self._recipe_root(records["recipes"], recipe["id"])
                if root not in latest or recipe["revision"] > latest[root]["revision"]:
                    latest[root] = recipe
            refs = [{"id": item["id"], "name": item["name"], "revision": item["revision"],
                     "archived": bool(records["rule_states"].get(root, {}).get("archived"))}
                    for root, item in latest.items() if item.get("connection_ref") == connection_id]
            current_ids = {item["id"] for item in refs}
            historical = sorted(item["id"] for item in records["recipes"].values()
                                if item.get("connection_ref") == connection_id and item["id"] not in current_ids)
            defaults = state.get("connection_defaults", {})
            return {"connection": self._connection_summary(connection, defaults),
                    "token": self._connection_signature(state), "recipes": refs,
                    "historical_recipe_ids": historical,
                    "default_revision": defaults.get(connection["provider_id"], {}).get("revision", 0),
                    "replacements": [self._connection_summary(item, defaults)
                        for item in records["connections"].values()
                        if item["provider_id"] == connection["provider_id"] and item["id"] != connection_id]}

    def connection_deletion_receipt(self, token: str) -> dict | None:
        with self._locked():
            return deepcopy(self._read().get("connection_deletions", {}).get(token))

    def prepare_connection_deletion(self, connection_id: str, token: str, action: str,
                                    replacement_ref: str | None = None, *, request_token: str | None = None,
                                    catalog_token: str = "", recipe_ids: list[str] | None = None,
                                    catalog_references: list[dict] | None = None) -> dict:
        """Write only new immutable revisions first; retain the old connection on any failure."""
        if action not in {"replace", "detach"} or (action == "replace") != bool(replacement_ref):
            raise ValueError("Select a replacement connection or explicitly leave references missing")
        request_token = request_token or token
        with self._locked():
            state = self._read()
            receipts = state.setdefault("connection_deletions", {})
            if request_token in receipts:
                receipt = receipts[request_token]
                if (receipt["connection_id"], receipt["action"], receipt["replacement_ref"]) != (connection_id, action, replacement_ref):
                    raise ConnectionConflictError("Deletion confirmation belongs to a different choice")
                return deepcopy(receipt)
            if token != self._connection_signature(state):
                raise ConnectionConflictError("Connection references changed; review deletion again")
            records = state["collections"]
            connection = records["connections"].get(connection_id)
            if connection is None:
                raise KeyError("Connection no longer exists")
            if replacement_ref:
                replacement = records["connections"].get(replacement_ref)
                if (replacement is None or replacement_ref == connection_id
                        or replacement["provider_id"] != connection["provider_id"]):
                    raise ValueError("Replacement must be another connection for the same engine")
            latest = {}
            for recipe in records["recipes"].values():
                root = self._recipe_root(records["recipes"], recipe["id"])
                if root not in latest or recipe["revision"] > latest[root]["revision"]:
                    latest[root] = recipe
            revisions = []
            if action == "replace":
                for old in latest.values():
                    if old.get("connection_ref") != connection_id:
                        continue
                    new = {**deepcopy(old), "id": str(uuid4()), "previous_id": old["id"],
                           "revision": old["revision"] + 1, "connection_ref": replacement_ref,
                           "created_at": _now(), "updated_at": _now()}
                    self._validate("recipes", new)
                    records["recipes"][new["id"]] = new
                    revisions.append({"previous_id": old["id"], "id": new["id"], "revision": new["revision"]})
            receipt = {"request_token": request_token, "connection_id": connection_id,
                       "provider_id": connection["provider_id"], "action": action,
                       "replacement_ref": replacement_ref, "catalog_token": catalog_token,
                       "catalog_references": deepcopy(catalog_references or []),
                       "recipe_ids": list(recipe_ids or []), "recipe_revisions": revisions,
                       "recipe_id_map": {item["previous_id"]: item["id"] for item in revisions},
                       "guard_token": self._connection_signature(state), "state": "prepared"}
            receipts[request_token] = receipt
            self._write(state)
            return deepcopy(receipt)

    def finalize_connection_deletion(self, receipt: dict) -> dict:
        """Remove the connection record only after all selected reference migrations succeeded."""
        with self._locked():
            state = self._read()
            saved = state.get("connection_deletions", {}).get(receipt.get("request_token"))
            if saved is None or saved["connection_id"] != receipt.get("connection_id"):
                raise ConnectionConflictError("Deletion preparation is unavailable; review again")
            if saved["state"] == "completed":
                return deepcopy(saved["result"])
            if saved["guard_token"] != self._connection_signature(state):
                raise ConnectionConflictError("Connection or rules changed during deletion; old connection was retained")
            records = state["collections"]
            old = records["connections"].pop(saved["connection_id"])
            defaults = state.setdefault("connection_defaults", {})
            previous = defaults.get(old["provider_id"], {})
            remaining = any(item["provider_id"] == old["provider_id"] for item in records["connections"].values())
            if previous.get("connection_ref") == old["id"] or not remaining:
                defaults[old["provider_id"]] = {"provider_id": old["provider_id"],
                    "connection_ref": saved["replacement_ref"], "revision": previous.get("revision", 0) + 1}
            result = {"deleted_connection_id": old["id"], "action": saved["action"],
                      "recipe_revisions": saved["recipe_revisions"], "defaults": deepcopy(list(defaults.values()))}
            saved.update(state="completed", result=result)
            self._write(state)
            return deepcopy(result)

    @staticmethod
    def _validate(collection: str, record: dict) -> None:
        _no_secrets(record)
        # JSON round trip also rejects runtime objects and non-finite numbers.
        json.dumps(record, allow_nan=False)
        if collection == "voices":
            if not str(record.get("name", "")).strip():
                raise ValueError("Voice name is required")
            bindings = record.get("bindings", [])
            if not isinstance(bindings, list):
                raise ValueError("Voice bindings must be a list")
            for binding in bindings:
                if not isinstance(binding, dict) or not binding.get("provider_id"):
                    raise ValueError("Voice bindings require a provider_id")
                for variant in binding.get("variants", []):
                    SpeechStore._variant(variant)
        elif collection == "recipes":
            for key in ("name", "voice_id", "provider_id", "model"):
                if not record.get(key):
                    raise ValueError(f"Recipe requires {key}")
            SpeechStore._variant(record.get("variant"))
            options = record.get("provider_options", {})
            if not isinstance(options, dict) or options.get("schema_version") != 1:
                raise ValueError("Recipe provider_options require schema_version=1")
        elif collection == "plans":
            validate_plan(record.get("text"), record)

    @staticmethod
    def _variant(variant: dict) -> None:
        if not isinstance(variant, dict) or variant.get("kind") not in {"hosted", "builtin", "reference", "design", "default"}:
            raise ValueError("Invalid voice variant")
        if not isinstance(variant.get("value"), str) or not variant["value"].strip():
            raise ValueError("Voice variant value is required")
        if variant.get("style", "normal") not in {"normal", "soft", "whisper"}:
            raise ValueError("Invalid voice variant style")

    def create(self, collection: str, data: dict) -> dict:
        self._collection(collection)
        record = deepcopy(data)
        record.setdefault("id", str(uuid4()))
        if not isinstance(record["id"], str) or not record["id"]:
            raise ValueError("Record id must be a nonempty string")
        record.setdefault("revision", 1)
        record["created_at"] = _now()
        record["updated_at"] = record["created_at"]
        self._validate(collection, record)
        with self._locked():
            state = self._read()
            if collection == "recipes":
                self._check_recipe_connection(state, record)
            if record["id"] in state["collections"][collection]:
                raise ValueError("Record already exists; create a new revision")
            previous = state["collections"][collection].get(record.get("previous_id"))
            expected = previous["revision"] + 1 if previous else 1
            if record.get("previous_id") and previous is None:
                raise ValueError("Previous revision does not exist")
            if type(record["revision"]) is not int or record["revision"] != expected:
                raise ValueError("Invalid record revision")
            state["collections"][collection][record["id"]] = record
            self._write(state)
        return deepcopy(record)

    def update(self, collection: str, id: str, data: dict, expected_revision: int | None = None) -> dict:
        self._collection(collection)
        with self._locked():
            state = self._read()
            old = state["collections"][collection].get(id)
            if old is None:
                raise KeyError(id)
            if expected_revision is not None and old["revision"] != expected_revision:
                raise ValueError("Record revision conflict; reload before saving")
            if collection == "plans" and data.get("text", old["text"]) != old["text"]:
                raise ValueError("Create a new plan for changed source text")
            record = {**old, **deepcopy(data)}
            record["id"] = str(uuid4()) if collection in IMMUTABLE else id
            record["revision"] = old["revision"] + 1
            record["updated_at"] = _now()
            record["created_at"] = record["updated_at"] if collection in IMMUTABLE else old["created_at"]
            if collection in IMMUTABLE:
                record["previous_id"] = id
            self._validate(collection, record)
            if collection == "recipes":
                self._check_recipe_connection(state, record)
            state["collections"][collection][record["id"]] = record
            self._write(state)
        return deepcopy(record)

    def build_plan(self, text: str) -> dict:
        return self.create("plans", build_plan(text))

    @staticmethod
    def _check_recipe_connection(state: dict, recipe: dict) -> None:
        ref = recipe.get("connection_ref")
        if not ref or ref == "engine-default-" + str(recipe.get("provider_id")):
            return
        connection = state["collections"]["connections"].get(ref)
        if connection is None or connection["provider_id"] != recipe.get("provider_id"):
            raise ConnectionConflictError("Connection was removed or changed before saving; select a connection again")

    def ensure_builtin_recipe(self, key: str, recipe_data: dict, *, add: bool = False) -> dict | None:
        """Seed once atomically; a durable marker survives archive and physical cleanup.

        Explicit add preserves an existing active revision or creates a fresh
        ordinary recipe. It never restores deleted/archived user records.
        """
        with self._locked():
            state = self._read()
            markers = state.setdefault("builtin_recipes", {})
            records = state["collections"]
            if key in markers:
                if not add:
                    return None
                root = markers[key]["recipe_id"]
                revisions = [item for item in records["recipes"].values()
                             if self._recipe_root(records["recipes"], item["id"]) == root]
                if revisions and not records["rule_states"].get(root, {}).get("archived"):
                    latest = max(revisions, key=lambda item: item["revision"])
                    return deepcopy(latest)
            timestamp = _now()
            voice = {"id": str(uuid4()), "name": recipe_data["name"], "bindings": [],
                     "revision": 1, "created_at": timestamp, "updated_at": timestamp}
            recipe = {**deepcopy(recipe_data), "id": str(uuid4()), "voice_id": voice["id"],
                      "revision": 1, "created_at": timestamp, "updated_at": timestamp}
            self._validate("voices", voice)
            self._validate("recipes", recipe)
            self._check_recipe_connection(state, recipe)
            records["voices"][voice["id"]] = voice
            records["recipes"][recipe["id"]] = recipe
            markers[key] = {"recipe_id": recipe["id"]}
            self._write(state)
            return deepcopy(recipe)

    def create_rule(self, voice_data: dict | None, recipe_data: dict) -> dict:
        with self._locked():
            state = self._read()
            records = state["collections"]
            recipe = deepcopy(recipe_data)
            self._check_recipe_connection(state, recipe)
            variant = recipe.get("variant") or {}
            if variant.get("kind") == "reference":
                asset = records["assets"].get(variant.get("value"))
                if asset is None or asset.get("archived"):
                    raise ValueError("Reference asset is missing or archived; reload before saving")
            if voice_data is not None:
                voice = {**deepcopy(voice_data), "id": str(uuid4()), "revision": 1, "created_at": _now(), "updated_at": _now()}
                self._validate("voices", voice)
                records["voices"][voice["id"]] = voice
                recipe["voice_id"] = voice["id"]
            elif recipe.get("voice_id") not in records["voices"]:
                raise ValueError("Unknown rule voice")
            previous = records["recipes"].get(recipe.get("previous_id"))
            if recipe.get("previous_id") and previous is None:
                raise ValueError("Unknown previous recipe")
            if previous and any(item.get("previous_id") == previous["id"] for item in records["recipes"].values()):
                raise ValueError("Rule revision changed; reload before saving")
            if previous and previous["voice_id"] != recipe["voice_id"]:
                raise ValueError("Recipe revision must retain its voice")
            recipe.update(id=str(uuid4()), revision=previous["revision"] + 1 if previous else 1, created_at=_now(), updated_at=_now())
            self._validate("recipes", recipe)
            records["recipes"][recipe["id"]] = recipe
            self._write(state)
            return deepcopy(recipe)

    @staticmethod
    def _recipe_root(records: dict, id: str) -> str:
        seen = set()
        while records[id].get("previous_id"):
            if id in seen:
                raise ValueError("Cyclic recipe revisions")
            seen.add(id)
            id = records[id]["previous_id"]
        return id

    def active_recipes(self, include_archived: bool = False) -> list[dict]:
        with self._locked():
            records = self._read()["collections"]
            latest = {}
            for recipe in records["recipes"].values():
                root = self._recipe_root(records["recipes"], recipe["id"])
                if not include_archived and records["rule_states"].get(root, {}).get("archived"):
                    continue
                if root not in latest or recipe["revision"] > latest[root]["revision"]:
                    latest[root] = recipe
            result = deepcopy(list(latest.values()))
            if include_archived:
                for recipe in result:
                    root = self._recipe_root(records["recipes"], recipe["id"])
                    recipe["archived"] = bool(records["rule_states"].get(root, {}).get("archived"))
            return result

    def validate_plan(self, text: str, proposed: dict) -> dict:
        return self.create("plans", validate_plan(text, proposed))

    @_reference_file_operation
    def import_reference(self, path: str | Path, start: float, end: float | None, transcript: str, language: str, confirmed: bool = True,
                         *, name: str = "", notes: str = "", gain_db: float = 0, fade_in: float = 0,
                         fade_out: float = 0, preview: bool = False) -> dict:
        import numpy as np
        import soundfile as sf
        if not isinstance(name, str) or not isinstance(notes, str):
            raise ValueError("Reference name and notes must be text")
        if not isinstance(transcript, str) or type(confirmed) is not bool:
            raise ValueError("Invalid reference transcript or confirmation")
        confirmed = confirmed and bool(transcript.strip())
        if not isinstance(language, str) or not language.strip():
            raise ValueError("Reference language is required")
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("Reference must be an audio file")
        start, end = float(start), None if end is None else float(end)
        gain_db, fade_in, fade_out = float(gain_db), float(fade_in), float(fade_out)
        if not all(math.isfinite(v) for v in (gain_db, fade_in, fade_out)) or not -24 <= gain_db <= 12 or min(fade_in, fade_out) < 0:
            raise ValueError("Invalid gain or fades")
        if not math.isfinite(start) or start < 0 or (end is not None and (not math.isfinite(end) or end <= start)):
            raise ValueError("Invalid reference interval")
        # Copy before decoding so later edits to the source cannot mutate assets.
        destination_root = self.root / "_staging" if preview else self.assets_root
        destination_root.mkdir(parents=True, exist_ok=True)
        directory = destination_root / str(uuid4())
        directory.mkdir()
        try:
            original_path = str(source)
            parent_asset = next((a for a in self.list("assets") if Path(a.get("path", "")).resolve() == source), None)
            inspection_id = None
            staging = (self.root / "_staging").resolve()
            if source.is_relative_to(staging) and (source.parent / "inspection.json").is_file():
                inspected = self.get_inspection(source.parent.name)
                if inspected.get("parent_asset_id"):
                    parent_asset = self.get("assets", inspected["parent_asset_id"])
                if source not in {Path(inspected["path"]).resolve(), Path(inspected["source_path"]).resolve()}:
                    raise ValueError("Unknown staged reference file")
                original_path = inspected["original_path"]
                inspection_id = inspected["id"]
                source = Path(inspected["source_path"])
            copied = directory / ("source" + source.suffix.lower())
            shutil.copyfile(source, copied)
            source_hash = _hash_file(copied)
            if inspection_id and source_hash != inspected.get("source_sha256", inspected["sha256"]):
                raise ValueError("Staged source changed while importing")
            playable = _readable_audio(copied, directory)
            with sf.SoundFile(playable) as audio:
                rate = audio.samplerate
                if end is None:
                    end = audio.frames / rate
                if end > audio.frames / rate:
                    raise ValueError("Reference interval exceeds source audio")
                first, last = round(start * rate), round(end * rate)
                if last <= first:
                    raise ValueError("Reference interval contains no samples")
                audio.seek(first)
                samples = audio.read(last - first, dtype="float32", always_2d=True)
                source_frames = audio.frames
            if fade_in + fade_out > len(samples) / rate:
                raise ValueError("Fade durations exceed selected audio")
            samples *= 10 ** (gain_db / 20)
            for seconds, reverse in ((fade_in, False), (fade_out, True)):
                count = min(len(samples), round(seconds * rate))
                if count:
                    ramp = np.linspace(0, 1, count, dtype="float32")
                    if reverse:
                        samples[-count:] *= ramp[::-1, None]
                    else:
                        samples[:count] *= ramp[:, None]
            peak = float(np.max(np.abs(samples)))
            if not math.isfinite(peak) or peak > 1.0:
                raise ValueError("处理结果将产生削波，请降低增益；不会自动限幅")
            crop = directory / "reference.wav"
            sf.write(crop, samples, rate, subtype="FLOAT")
            mono_peak = np.max(np.abs(samples), axis=1)
            peaks = [float(np.max(chunk)) for chunk in np.array_split(mono_peak, min(512, len(mono_peak))) if len(chunk)]
            record = {
                "kind": "reference", "name": name.strip() or Path(original_path).stem, "notes": notes, "path": str(crop),
                "source_path": str(copied), "original_path": original_path, "inspection_id": inspection_id,
                "source_playback_path": str(playable), "source_playback_sha256": _hash_file(playable),
                "sha256": _hash_file(crop), "source_sha256": source_hash,
                "start": first / rate, "end": last / rate, "start_frame": first,
                "end_frame": last, "sample_rate": rate, "channels": int(samples.shape[1]),
                "duration": len(samples) / rate, "source_duration": source_frames / rate,
                "transcript": transcript, "language": language, "confirmed": confirmed,
                "parent_asset_id": parent_asset["id"] if parent_asset else None,
                "source_processing": {"parent_asset_id": parent_asset["id"] if parent_asset else None,
                                      "input_sha256": source_hash, "start": first / rate, "end": last / rate},
                "processing": {"gain_db": gain_db, "fade_in": fade_in, "fade_out": fade_out},
                "peak": peak, "headroom_db": -20 * math.log10(peak) if peak > 0 else None,
                "peaks": peaks, "processing_version": 1,
            }
            if preview:
                record.update(id=directory.name, staged=True)
                self._atomic_json(directory / "inspection.json", record)
                return record
            return self.create("assets", record)
        except Exception:
            # Only our newly allocated directory; never source or existing assets.
            shutil.rmtree(directory)
            raise

    def reference_metadata(self, id: str, data: dict) -> dict:
        """Rename without modifying immutable audio, IDs or legacy archive data."""
        if set(data) - {"name", "notes"}:
            raise ValueError("Only reference name and notes can change; use confirmed deletion to delete")
        if "name" in data and (not isinstance(data["name"], str) or not data["name"].strip()):
            raise ValueError("Reference name is required")
        if "notes" in data and not isinstance(data["notes"], str):
            raise ValueError("Reference notes must be text")
        with self._locked():
            state = self._read()
            record = state["collections"]["assets"][id]
            record.update(deepcopy(data), updated_at=_now())
            self._write(state)
            return deepcopy(record)

    @_reference_file_operation
    def inspect_reference(self, path: str | Path) -> dict:
        """Stage a source for listening and waveform selection, without adopting it."""
        import numpy as np
        import soundfile as sf
        original = Path(path).resolve(strict=True)
        if not original.is_file():
            raise ValueError("Reference must be an audio file")
        original_path = str(original)
        companion_source_path = None
        staging = (self.root / "_staging").resolve()
        if original.is_relative_to(staging) and (original.parent / "inspection.json").is_file():
            inspected = self.get_inspection(original.parent.name)
            if original not in {Path(inspected["path"]).resolve(), Path(inspected["source_path"]).resolve()}:
                raise ValueError("Unknown staged reference file")
            original_path = inspected["original_path"]
            if not inspected.get("processing"):
                companion_source_path = inspected.get("companion_source_path", original_path)
        elif not original.is_relative_to(self.root.resolve()):
            companion_source_path = original_path
        parent_asset = next((a for a in self.list("assets") if Path(a.get("path", "")).resolve() == original), None)
        id = str(uuid4())
        directory = self.root / "_staging" / id
        directory.mkdir(parents=True)
        copied = directory / ("source" + original.suffix.lower())
        try:
            shutil.copyfile(original, copied)
            playable = _readable_audio(copied, directory)
            with sf.SoundFile(playable) as audio:
                rate, frames, channels = audio.samplerate, audio.frames, audio.channels
                if frames <= 0:
                    raise ValueError("Reference audio is empty")
                # Bounded memory even for long originals: one peak per bin.
                bin_size = max(1, math.ceil(frames / 1024))
                peaks = []
                while audio.tell() < frames:
                    block = audio.read(bin_size, dtype="float32", always_2d=True)
                    peaks.append(float(np.max(np.abs(block))))
            record = {"id": id, "path": str(playable), "source_path": str(copied),
                      "parent_asset_id": parent_asset["id"] if parent_asset else None,
                      "source_playback_path": str(playable), "source_playback_sha256": _hash_file(playable),
                      "original_path": original_path, "companion_source_path": companion_source_path,
                      "duration": frames / rate,
                      "sample_rate": rate, "channels": channels, "peaks": peaks,
                      "sha256": _hash_file(playable), "source_sha256": _hash_file(copied), "staged": True}
            record["companion_subtitles"] = [
                {"name": candidate.name, "format": candidate.suffix[1:]}
                for candidate in companion_subtitle_paths(companion_source_path)
            ]
            self._atomic_json(directory / "inspection.json", record)
            return record
        except Exception:
            shutil.rmtree(directory)
            raise

    def get_inspection(self, id: str) -> dict:
        if not isinstance(id, str) or not re.fullmatch(r"[0-9a-f-]{36}", id):
            raise ValueError("Invalid inspection id")
        path = self.root / "_staging" / id / "inspection.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        audio = Path(record["path"]).resolve(strict=True)
        if not audio.is_relative_to(path.parent.resolve()) or _hash_file(audio) != record["sha256"]:
            raise ValueError("Staged reference changed since inspection")
        original = Path(record["source_path"]).resolve(strict=True)
        if not original.is_relative_to(path.parent.resolve()) or _hash_file(original) != record.get("source_sha256", record["sha256"]):
            raise ValueError("Staged original changed since inspection")
        return record

    def reference_audio_path(self, id: str, *, source: bool = False) -> Path:
        asset = self.get("assets", id)
        path = Path(asset["source_path" if source else "path"]).resolve(strict=True)
        if not path.is_relative_to(self.assets_root.resolve()):
            raise ValueError("Asset is outside the owned audio directory")
        expected = asset["source_sha256" if source else "sha256"]
        if _hash_file(path) != expected:
            raise ValueError("Reference audio has changed since import")
        return path

    def backup_for_import(self, sources: list[Path]) -> Path:
        """Back up source files and existing store before an explicit import."""
        folder = self.root / "backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex)
        folder.mkdir(parents=True)
        manifest = []
        with self._locked():
            if self.path.exists():
                shutil.copyfile(self.path, folder / "store.json")
            for index, source in enumerate(sources):
                source = Path(source).resolve(strict=True)
                destination = folder / f"{index}-{source.name}"
                shutil.copyfile(source, destination)
                manifest.append({"source": str(source), "backup": destination.name, "sha256": _hash_file(destination)})
            self._atomic_json(folder / "manifest.json", {"created_at": _now(), "files": manifest})
        return folder
