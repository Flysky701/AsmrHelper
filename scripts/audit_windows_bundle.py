"""Read-only integrity and privacy audit of a staged backend; never prints contents."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    root = args.backend.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    warnings = []
    expected = {entry["path"] for entry in manifest["files"]}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            errors.append({"path": entry["path"], "reason": "missing"})
            continue
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            errors.append({"path": entry["path"], "reason": "hash mismatch"})
    for name in sorted(actual - expected - {"manifest.json"}):
        errors.append({"path": name, "reason": "unmanifested file"})
    denied_parts = {".git", "voice_lab", "__pycache__"}
    for name in sorted(actual):
        path = root / name
        if denied_parts.intersection(path.relative_to(root).parts) or path.name in {"config.json", "voice_profiles.json", ".env"} or path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".pyc"}:
            errors.append({"path": name, "reason": "private/runtime filename"})
        if name.startswith("app/") and path.suffix.lower() in {".py", ".json", ".yaml", ".toml", ".md"}:
            content = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?i)(sk-[a-z0-9]{24,}|ghp_[a-z0-9]{25,}|github_pat_[a-z0-9_]{30,})", content):
                errors.append({"path": name, "reason": "credential-like token"})
            if re.search(r"(?i)[a-z]:[\\/](?:Users|Projects|WorkSpace)[\\/]", content):
                warnings.append({"path": name, "reason": "absolute development path; review example/source context"})
    result = {"version": manifest["version"], "files": len(actual), "errors": errors, "warnings": warnings, "passed": not errors}
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
