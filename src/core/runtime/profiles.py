from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.config import PROJECT_ROOT


@dataclass(frozen=True)
class RuntimeProfile:
    id: str
    isolated: bool
    environment_dir: Path | None
    python_executable: Path
    project_extra: str | None = None
    cuda_torch: bool = False


class RuntimeProfileResolver:
    """Resolve named Python environments without persisting machine paths."""

    _PROFILE_EXTRAS = {
        "qwen_tts": "qwen3",
        "qwen_asr": "qwen_asr",
        "fun_asr": "funasr",
    }
    # Qwen3-TTS has a verified CUDA runtime. ASR runtimes declare ordinary
    # torch explicitly in the model catalog so CPU-only hosts remain usable.
    _CUDA_TORCH_PROFILES = {"qwen_tts"}

    _ALIASES = {
        "": "main",
        "main": "main",
        "python_package_local": "main",
        "qwen_tts": "qwen_tts",
        "qwen_asr": "qwen_asr",
        "fun_asr": "fun_asr",
    }

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        self._probe_cache: dict[tuple[str, str], tuple[float, bool]] = {}
        self._probe_lock = threading.Lock()

    def resolve(self, profile_id: str | None) -> RuntimeProfile:
        normalized = self._ALIASES.get(str(profile_id or "").strip())
        if normalized is None:
            raise ValueError(f"unknown runtime profile: {profile_id}")
        if normalized == "main":
            return RuntimeProfile(
                id="main",
                isolated=False,
                environment_dir=None,
                python_executable=Path(sys.executable).resolve(),
            )

        environment_dir = self.project_root / ".runtimes" / normalized
        executable = (
            environment_dir / "Scripts" / "python.exe"
            if os.name == "nt"
            else environment_dir / "bin" / "python"
        )
        return RuntimeProfile(
            id=normalized,
            isolated=True,
            environment_dir=environment_dir,
            python_executable=executable,
            project_extra=self._PROFILE_EXTRAS[normalized],
            cuda_torch=normalized in self._CUDA_TORCH_PROFILES,
        )

    def ensure_environment(self, profile_id: str) -> RuntimeProfile:
        profile = self.resolve(profile_id)
        if not profile.isolated or profile.python_executable.is_file():
            return profile

        uv_path = shutil.which("uv")
        if not uv_path:
            raise RuntimeError("uv is required to create isolated runtime environments")
        assert profile.environment_dir is not None
        profile.environment_dir.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                uv_path,
                "venv",
                str(profile.environment_dir),
                "--python",
                sys.executable,
                "--clear",
            ],
            cwd=str(self.project_root),
            env=self.subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if result.returncode != 0 or not profile.python_executable.is_file():
            detail = (result.stderr or result.stdout or "unknown error").strip()[-1000:]
            raise RuntimeError(f"failed to create runtime {profile.id}: {detail}")
        return profile

    def build_bootstrap_commands(self, profile: RuntimeProfile) -> list[list[str]]:
        if not profile.cuda_torch:
            return []
        uv_path = shutil.which("uv")
        if not uv_path:
            raise RuntimeError("uv is required to install the CUDA runtime")
        return [[
            uv_path,
            "pip",
            "install",
            "--python",
            str(profile.python_executable),
            "--index",
            "https://download.pytorch.org/whl/cu126",
            "torch==2.10.0+cu126",
            "torchaudio==2.10.0+cu126",
        ]]

    def check_modules(self, profile_id: str | None, modules: Iterable[str]) -> bool:
        profile = self.resolve(profile_id)
        if not profile.python_executable.is_file():
            return False
        unique_modules = list(dict.fromkeys(str(module) for module in modules if module))
        if not unique_modules:
            return True
        cache_key = (profile.id, "modules:" + ",".join(unique_modules))
        cached = self._get_cached_probe(cache_key)
        if cached is not None:
            return cached
        script = (
            "import importlib, json\n"
            f"modules = {unique_modules!r}\n"
            "result = {name: bool(importlib.import_module(name)) for name in modules}\n"
            "print('__ASMR_RUNTIME_PROBE__' + json.dumps(result))\n"
        )
        result = subprocess.run(
            [str(profile.python_executable), "-c", script],
            cwd=str(self.project_root),
            env=self.subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return False
        try:
            line = next(
                line for line in reversed(result.stdout.splitlines())
                if line.startswith("__ASMR_RUNTIME_PROBE__")
            )
            available = all(json.loads(line.removeprefix("__ASMR_RUNTIME_PROBE__")).values())
            self._set_cached_probe(cache_key, available)
            return available
        except (json.JSONDecodeError, AttributeError, StopIteration):
            return False

    def has_cuda(self, profile_id: str | None) -> bool:
        profile = self.resolve(profile_id)
        if not profile.python_executable.is_file():
            return False
        cache_key = (profile.id, "cuda")
        cached = self._get_cached_probe(cache_key)
        if cached is not None:
            return cached
        result = subprocess.run(
            [
                str(profile.python_executable),
                "-c",
                "import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)",
            ],
            cwd=str(self.project_root),
            env=self.subprocess_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        available = result.returncode == 0
        self._set_cached_probe(cache_key, available)
        return available

    def clear_probe_cache(self, profile_id: str | None = None) -> None:
        normalized = self.resolve(profile_id).id if profile_id is not None else None
        with self._probe_lock:
            if normalized is None:
                self._probe_cache.clear()
            else:
                self._probe_cache = {
                    key: value for key, value in self._probe_cache.items() if key[0] != normalized
                }

    def _get_cached_probe(self, key: tuple[str, str]) -> bool | None:
        with self._probe_lock:
            cached = self._probe_cache.get(key)
        if cached is None or time.monotonic() - cached[0] > 60.0:
            return None
        return cached[1]

    def _set_cached_probe(self, key: tuple[str, str], value: bool) -> None:
        with self._probe_lock:
            self._probe_cache[key] = (time.monotonic(), value)

    def subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("UV_CACHE_DIR", str(self.project_root / ".uv-cache"))
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env


_resolver: RuntimeProfileResolver | None = None
_lock = threading.Lock()


def get_runtime_profile_resolver() -> RuntimeProfileResolver:
    global _resolver
    if _resolver is None:
        with _lock:
            if _resolver is None:
                _resolver = RuntimeProfileResolver()
    return _resolver
