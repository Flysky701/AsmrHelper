"""Machine-local probe results, invalidated by runtime changes rather than startup."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from src.config import APP_ROOT


def signature(profile, project_root: Path) -> str:
    executable = profile.python_executable
    root = profile.environment_dir or Path(sys.prefix)
    sites = [root / "Lib" / "site-packages", *root.glob("lib/python*/site-packages")]
    paths = [executable, root / "pyvenv.cfg", APP_ROOT / "pyproject.toml"]
    for site in sites:
        paths.append(site)
        if site.is_dir():
            for child in sorted(site.iterdir()):
                paths.append(child)
                if child.is_dir() and not child.name.endswith(".dist-info"):
                    paths.append(child / "__init__.py")
                if child.name.endswith(".dist-info"):
                    paths.append(child / "METADATA")
    if os.name == "nt":
        paths.append(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "nvcuda.dll")
    else:
        paths.append(Path("/proc/driver/nvidia/version"))
    identities = []
    for path in paths:
        try:
            stat = path.stat()
            identities.append((str(path), stat.st_size, stat.st_mtime_ns))
        except OSError:
            identities.append((str(path), None, None))
    data = {"version": 1, "files": identities,
            "env": {key: os.environ.get(key) for key in
                    ("CUDA_VISIBLE_DEVICES", "PYTHONPATH", "CUDA_PATH", "PATH")}}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class ProbeCache:
    def __init__(self, root: Path):
        self.root = root / ".cache" / "runtime-probes"

    def path(self, key):
        digest = hashlib.sha256(key[1].encode()).hexdigest()
        return self.root / key[0] / f"{digest}.json"

    def read(self, key, fingerprint):
        try:
            value = json.loads(self.path(key).read_text(encoding="utf-8"))
            if (isinstance(value, dict) and value.get("version") == 1
                    and value.get("signature") == fingerprint
                    and (type(value.get("available")) is bool or isinstance(value.get("error"), str))):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return None

    def write(self, key, record):
        path = self.path(key)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            # A read-only cache must not turn a successful probe into a failure.
            pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self, profile_id=None):
        directory = self.root / profile_id if profile_id else self.root
        if directory.is_dir():
            for path in directory.glob("*.json" if profile_id else "*/*.json"):
                path.unlink(missing_ok=True)
