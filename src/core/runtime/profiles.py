from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.config import PROJECT_ROOT
from .probe_cache import ProbeCache, signature


logger = logging.getLogger(__name__)


class RuntimeProbeError(RuntimeError):
    """Raised when runtime availability could not be determined reliably."""


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
        "voxcpm2": "voxcpm2",
    }
    _CUDA_TORCH_PROFILES = {"main", "qwen_asr", "fun_asr", "qwen_tts", "voxcpm2"}

    _ALIASES = {
        "": "main",
        "main": "main",
        "python_package_local": "main",
        "qwen_tts": "qwen_tts",
        "qwen_asr": "qwen_asr",
        "fun_asr": "fun_asr",
        "voxcpm2": "voxcpm2",
    }

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        self._probe_cache = ProbeCache(self.project_root)
        self._probe_records: dict[tuple[str, str], dict] = {}
        self._probe_flights: dict[str, threading.RLock] = {}
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

    def compute_mode(self) -> str:
        mode = os.environ.get("ASMR_HELPER_COMPUTE")
        path = self.project_root / "config" / "runtime_install.json"
        if mode is None:
            mode = json.loads(path.read_text(encoding="utf-8")).get("compute", "auto") if path.is_file() else "auto"
        if mode not in {"auto", "cpu", "cuda"}:
            raise ValueError("compute must be auto, cpu, or cuda")
        return mode

    def save_compute_mode(self, mode: str) -> None:
        if mode not in {"auto", "cpu", "cuda"}:
            raise ValueError("compute must be auto, cpu, or cuda")
        path = self.project_root / "config" / "runtime_install.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data.update(compute=mode)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def resolve_compute_target(self) -> str:
        mode = self.compute_mode()
        if mode == "cpu":
            return "cpu"
        capability = self._detect_nvidia_compute_capability()
        if capability is None:
            if mode == "cuda":
                raise RuntimeError("unable to detect NVIDIA GPU compute capability; CUDA was explicitly requested")
            return "cpu"
        return "cu128" if capability >= 12.0 else "cu126"

    def compute_constraints(self, target: str | None = None) -> Path:
        target = target or self.resolve_compute_target()
        if target not in {"cpu", "cu126", "cu128"}:
            raise ValueError("unknown compute target")
        path = self.project_root / ".runtimes" / f"torch-{target}-constraints.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"torch==2.10.0+{target}\ntorchaudio==2.10.0+{target}\n", encoding="utf-8")
        return path

    def build_bootstrap_commands(self, profile: RuntimeProfile) -> list[list[str]]:
        target = self.resolve_compute_target()
        uv_path = shutil.which("uv")
        if not uv_path:
            raise RuntimeError("uv is required to install the compute runtime")
        return [[
            uv_path,
            "pip",
            "install",
            "--python",
            str(profile.python_executable),
            "--index",
            f"https://download.pytorch.org/whl/{target}",
            f"torch==2.10.0+{target}",
            f"torchaudio==2.10.0+{target}",
        ]]

    def verify_compute(self, profile: RuntimeProfile) -> dict:
        target = self.resolve_compute_target()
        device = "cpu" if target == "cpu" else "cuda:0"
        script = (
            "import json, torch, torchaudio\n"
            f"target={target!r}\ndevice={device!r}\n"
            "assert torch.__version__ == '2.10.0+' + target, torch.__version__\n"
            "assert torchaudio.__version__ == '2.10.0+' + target, torchaudio.__version__\n"
            "assert (torch.version.cuda is None) == (target == 'cpu'), 'wrong torch build'\n"
            "a=torch.ones((16,16),device=device)\n"
            "assert (a @ a).sum().item() == 4096\n"
            "print('__ASMR_COMPUTE__'+json.dumps(dict(target=target,device=device,torch=torch.__version__,torchaudio=torchaudio.__version__,cuda=torch.version.cuda)))\n"
        )
        result = subprocess.run([str(profile.python_executable), "-c", script],
            cwd=str(self.project_root), env=self.subprocess_env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
        if result.returncode:
            raise RuntimeProbeError(f"compute verification failed for {profile.id}: {(result.stderr or result.stdout)[-1500:]}")
        try:
            line = next(line for line in reversed(result.stdout.splitlines()) if line.startswith("__ASMR_COMPUTE__"))
            return json.loads(line.removeprefix("__ASMR_COMPUTE__"))
        except (StopIteration, ValueError) as exc:
            raise RuntimeProbeError(f"invalid compute verification result for {profile.id}") from exc

    def _detect_nvidia_compute_capability(self) -> float | None:
        """Return the highest NVIDIA GPU compute capability reported by nvidia-smi."""
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return None
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=compute_cap",
                    "--format=csv,noheader,nounits",
                ],
                cwd=str(self.project_root),
                env=self.subprocess_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        capabilities: list[float] = []
        for line in result.stdout.splitlines():
            try:
                capabilities.append(float(line.strip()))
            except ValueError:
                continue
        return max(capabilities, default=None)

    def check_modules(self, profile_id: str | None, modules: Iterable[str]) -> bool:
        with self._flight_lock(profile_id):
            return self._check_modules(profile_id, modules)

    def _check_modules(self, profile_id: str | None, modules: Iterable[str]) -> bool:
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
            "def probe(name):\n"
            "    if name == 'funasr':\n"
            "        from funasr import AutoModel\n"
            "        return AutoModel is not None\n"
            "    return bool(importlib.import_module(name))\n"
            "result = {name: probe(name) for name in modules}\n"
            "print('__ASMR_RUNTIME_PROBE__' + json.dumps(result))\n"
        )
        try:
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
        except (OSError, subprocess.SubprocessError) as exc:
            detail = (f"runtime module probe failed: {profile.id} 依赖导入超过 30 秒，尚未确认可用性。"
                      if isinstance(exc, subprocess.TimeoutExpired) else f"runtime module probe failed: {exc}")
            logger.warning("%s profile=%s modules=%s error=%s", detail, profile.id, ",".join(unique_modules), exc)
            self._set_cached_probe_error(cache_key, detail)
            raise RuntimeProbeError(detail) from exc
        if result.returncode != 0:
            self._set_cached_probe(cache_key, False)
            return False
        try:
            line = next(
                line for line in reversed(result.stdout.splitlines())
                if line.startswith("__ASMR_RUNTIME_PROBE__")
            )
            available = all(json.loads(line.removeprefix("__ASMR_RUNTIME_PROBE__")).values())
            self._set_cached_probe(cache_key, available)
            return available
        except (json.JSONDecodeError, AttributeError, StopIteration) as exc:
            detail = "runtime module probe returned an invalid response"
            self._set_cached_probe_error(cache_key, detail)
            raise RuntimeProbeError(detail) from exc

    def has_cuda(self, profile_id: str | None) -> bool:
        with self._flight_lock(profile_id):
            return self._has_cuda(profile_id)

    def _has_cuda(self, profile_id: str | None) -> bool:
        profile = self.resolve(profile_id)
        if not profile.python_executable.is_file():
            return False
        cache_key = (profile.id, "cuda")
        cached = self._get_cached_probe(cache_key)
        if cached is not None:
            return cached
        try:
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
        except (OSError, subprocess.SubprocessError) as exc:
            detail = (f"runtime CUDA probe failed: {profile.id} CUDA 检查超过 30 秒，尚未确认可用性。"
                      if isinstance(exc, subprocess.TimeoutExpired) else f"runtime CUDA probe failed: {exc}")
            logger.warning("%s profile=%s error=%s", detail, profile.id, exc)
            self._set_cached_probe_error(cache_key, detail)
            raise RuntimeProbeError(detail) from exc
        available = result.returncode == 0
        self._set_cached_probe(cache_key, available)
        return available

    def clear_probe_cache(self, profile_id: str | None = None) -> None:
        normalized = self.resolve(profile_id).id if profile_id is not None else None
        profiles = [normalized] if normalized is not None else sorted(set(self._ALIASES.values()))
        # Finish any in-flight result before invalidating it, so an old probe
        # cannot repopulate a cache just cleared by installation or verification.
        with ExitStack() as stack:
            for profile in profiles:
                stack.enter_context(self._flight_lock(profile))
            with self._probe_lock:
                self._probe_records = {key: value for key, value in self._probe_records.items()
                                       if normalized is not None and key[0] != normalized}
                self._probe_cache.clear(normalized)

    def _flight_lock(self, profile_id):
        normalized = self.resolve(profile_id).id
        with self._probe_lock:
            return self._probe_flights.setdefault(normalized, threading.RLock())

    def _get_cached_probe(self, key: tuple[str, str]) -> bool | None:
        with self._probe_lock:
            fingerprint = signature(self.resolve(key[0]), self.project_root)
            cached = self._probe_records.get(key)
            if not cached or cached.get("signature") != fingerprint:
                cached = self._probe_cache.read(key, fingerprint)
            if not cached:
                return None
            self._probe_records[key] = cached
        if "error" in cached:
            try:
                checked = time.strftime("%Y-%m-%d %H:%M", time.localtime(cached["checked_at"]))
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                checked = "时间未知"
            raise RuntimeProbeError(f"{cached['error']}（上次检测：{checked}；点击“验证”重新检测）")
        return cached["available"]

    def _set_cached_probe(self, key: tuple[str, str], value: bool) -> None:
        with self._probe_lock:
            record = {"version": 1, "signature": signature(self.resolve(key[0]), self.project_root),
                      "checked_at": time.time(), "available": value}
            self._probe_records[key] = record
            self._probe_cache.write(key, record)

    def _set_cached_probe_error(self, key: tuple[str, str], detail: str) -> None:
        with self._probe_lock:
            record = {"version": 1, "signature": signature(self.resolve(key[0]), self.project_root),
                      "checked_at": time.time(), "error": detail}
            self._probe_records[key] = record
            self._probe_cache.write(key, record)

    def subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("UV_CACHE_DIR", str(self.project_root / ".uv-cache"))
        env.setdefault("UV_PYTHON_INSTALL_DIR", str(self.project_root / ".runtimes" / "python"))
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
