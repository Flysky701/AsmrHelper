"""Explicit offline import; never called by the running application.

Example: python scripts/import_voice_library.py --voices config/voice_profiles.json
         --connections config/config.json --connection-map approved-mappings.json
Mappings are keyed by old IDs and must state provider_id; URLs never infer it.
Clone mappings in --reference-map require confirmed transcript and language.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.speech.store import SpeechStore  # noqa: E402


def _load(path: Path | None) -> dict:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _old_path(value: str, project_root: Path) -> Path:
    value = str(value).replace("${PROJECT_ROOT}", str(project_root))
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def import_library(store: SpeechStore, *, voices_path: Path | None = None,
                   connections_path: Path | None = None, connection_map: dict | None = None,
                   reference_map: dict | None = None, project_root: Path = ROOT) -> dict:
    """Preserve legacy inputs, import explicit mappings and report every omission."""
    voices = _load(voices_path).get("profiles", [])
    connections_document = _load(connections_path)
    connections = connections_document.get("connection_profiles", connections_document)
    if isinstance(connections, dict):
        # The old settings representation may group profile rows by capability.
        rows = []
        for key in ("tts", "llm", "profiles"):
            value = connections.get(key, [])
            if isinstance(value, list):
                rows.extend(value)
            elif isinstance(value, dict):
                rows.extend(value.values())
        connections = rows
    if not isinstance(voices, list) or not isinstance(connections, list):
        raise ValueError("Legacy import inputs must contain profile lists")
    sources = [Path(path) for path in (voices_path, connections_path) if path]
    for voice in voices:
        if not isinstance(voice, dict):
            continue
        for key in ("ref_audio", "prompt_cache", "clone_manifest"):
            if voice.get(key):
                path = _old_path(voice[key], project_root)
                if path.is_file():
                    sources.append(path)
    # This is deliberately completed before the first store mutation.
    backup = store.backup_for_import(list(dict.fromkeys(sources)))
    report = {"backup": str(backup), "voices": [], "connections": [], "unmapped": [],
              "notes": ["Old prompt caches are backed up, not imported or executed; rebuild from confirmed references."]}
    for profile in voices:
        if not isinstance(profile, dict):
            report["unmapped"].append({"kind": "voice", "reason": "Invalid profile object"})
            continue
        old_id = str(profile.get("id", ""))
        try:
            if profile.get("engine") not in {"qwen3_custom", "qwen3_clone", "qwen3_design"}:
                raise ValueError("Legacy engine has no explicit Qwen mapping")
            category = profile.get("category")
            if category == "preset" and profile.get("speaker"):
                variant = {"kind": "builtin", "value": str(profile["speaker"]), "style": "normal"}
            elif category == "custom" and profile.get("design_instruct"):
                variant = {"kind": "design", "value": str(profile["design_instruct"]), "style": "normal"}
            elif category in {"clone", "custom"} and profile.get("ref_audio"):
                mapping = (reference_map or {}).get(old_id, {})
                if mapping.get("confirmed") is not True or not mapping.get("transcript") or not mapping.get("language"):
                    raise ValueError("Reference requires explicit confirmed transcript and language mapping")
                asset = store.import_reference(
                    _old_path(profile["ref_audio"], project_root), mapping["start"], mapping["end"],
                    mapping["transcript"], mapping["language"], confirmed=True,
                )
                variant = {"kind": "reference", "value": asset["id"], "style": mapping.get("style", "normal")}
            else:
                raise ValueError("No verified voice source; retained in backup")
            voice = store.create("voices", {
                "name": profile.get("name") or old_id, "description": profile.get("description", ""),
                "bindings": [{"provider_id": "qwen3", "variants": [variant]}],
                "default_binding": "qwen3", "imported_from": {"legacy_id": old_id, "backup": str(backup)},
            })
            report["voices"].append({"legacy_id": old_id, "id": voice["id"]})
            if profile.get("instruct"):
                report["unmapped"].append({"kind": "voice_instruction", "legacy_id": old_id,
                                           "reason": "Old instruct retained in backup; requires an explicit recipe intention"})
        except (ValueError, KeyError, OSError) as exc:
            report["unmapped"].append({"kind": "voice", "legacy_id": old_id, "reason": str(exc)})
    for profile in connections:
        if not isinstance(profile, dict):
            report["unmapped"].append({"kind": "connection", "reason": "Invalid connection object"})
            continue
        old_id = str(profile.get("id", ""))
        mapping = (connection_map or {}).get(old_id)
        if not isinstance(mapping, dict) or not mapping.get("provider_id"):
            report["unmapped"].append({"kind": "connection", "legacy_id": old_id,
                                      "reason": "Explicit provider mapping required; protocol is never inferred from URL"})
            continue
        try:
            # Only approved public fields cross the public migration boundary.
            public = {key: profile[key] for key in ("name", "base_url", "timeout", "model") if key in profile}
            public.update(mapping)
            public.setdefault("name", old_id)
            public["imported_from"] = {"legacy_id": old_id, "backup": str(backup)}
            credential_path = None
            SpeechStore._validate("connections", public)
            if profile.get("api_key"):
                reference = uuid4().hex
                credential_dir = store.root / "credentials"
                credential_dir.mkdir(exist_ok=True)
                credential_path = credential_dir / f"{reference}.json"
                SpeechStore._atomic_json(credential_path, {"api_key": profile["api_key"]})
                credential_path.chmod(0o600)
                public["credential_ref"] = reference
            try:
                connection = store.create("connections", public)
            except Exception:
                if credential_path:
                    credential_path.unlink(missing_ok=True)
                raise
            report["connections"].append({"legacy_id": old_id, "id": connection["id"], "credentials_imported": credential_path is not None})
        except (ValueError, KeyError, OSError) as exc:
            report["unmapped"].append({"kind": "connection", "legacy_id": old_id, "reason": str(exc)})
    stored = store.create("imports", report)
    SpeechStore._atomic_json(backup / "import-report.json", stored)
    return stored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", type=Path)
    parser.add_argument("--connections", type=Path)
    parser.add_argument("--connection-map", type=Path)
    parser.add_argument("--reference-map", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if not args.voices and not args.connections:
        parser.error("Supply --voices or --connections explicitly")
    report = import_library(SpeechStore(args.root), voices_path=args.voices, connections_path=args.connections,
                            connection_map=_load(args.connection_map), reference_map=_load(args.reference_map))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
