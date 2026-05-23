from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from src.config import PROJECT_ROOT

from .model_catalog import ModelEntry
from .model_status import ModelState, ModelStatusResolver

logger = logging.getLogger(__name__)


WHISPER_REPOS = {
    "faster-whisper-tiny": "Systran/faster-whisper-tiny",
    "faster-whisper-base": "Systran/faster-whisper-base",
    "faster-whisper-small": "Systran/faster-whisper-small",
    "faster-whisper-medium": "Systran/faster-whisper-medium",
    "faster-whisper-large-v3": "Systran/faster-whisper-large-v3",
}

QWEN3_REPOS = {
    "qwen3-custom-voice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "qwen3-voice-design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "qwen3-base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
}


class ModelInstaller:
    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or PROJECT_ROOT
        self._status = ModelStatusResolver()

    def verify_local_model(self, entry: ModelEntry) -> bool:
        return self._status.resolve(entry).status == ModelState.INSTALLED

    def remove_local_model(self, entry: ModelEntry) -> None:
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be removed: {entry.id}")
        if not entry.supports_remove:
            raise ValueError(f"model cannot be removed: {entry.id}")

        install_dir = entry.resolved_install_dir()
        if install_dir.exists():
            shutil.rmtree(install_dir)

    def install_local_model(self, entry: ModelEntry, mirror: Optional[str] = None, force: bool = False) -> bool:
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be installed: {entry.id}")
        if not entry.supports_install:
            raise ValueError(f"model cannot be installed: {entry.id}")

        status = self._status.resolve(entry)
        if status.status == ModelState.INSTALLED and not force:
            return True

        install_dir = entry.resolved_install_dir()
        install_dir.parent.mkdir(parents=True, exist_ok=True)

        strategy = entry.install_strategy
        if strategy == "whisper":
            return self._download_whisper(entry, mirror)
        if strategy == "qwen3":
            return self._download_qwen3(entry, mirror)
        if strategy == "huggingface_snapshot":
            return self._download_huggingface_snapshot(entry, mirror)
        raise ValueError(f"unknown install strategy: {strategy}")

    def _download_whisper(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror

        repo = WHISPER_REPOS[entry.id]
        target_dir = entry.resolved_install_dir()

        # Clean stale cache that may block re-download
        cache_dir = target_dir / ".cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)

        cmd = [
            sys.executable,
            "-c",
            "import os\n"
            "os.environ['PYTHONUTF8'] = '1'\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            f"from faster_whisper import download_model\n"
            f"download_model({repo!r}, output_dir={str(target_dir)!r})\n",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            env=env,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error("%s download failed (rc=%d): %s", entry.id, result.returncode, (result.stderr or "")[-500:])
        return result.returncode == 0 and self.verify_local_model(entry)

    def _download_qwen3(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror

        repo = QWEN3_REPOS[entry.id]
        target_dir = entry.resolved_install_dir()
        cmd = [
            sys.executable,
            "-c",
            "import os\n"
            "os.environ['PYTHONUTF8'] = '1'\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "from huggingface_hub import snapshot_download\n"
            f"snapshot_download({repo!r}, local_dir={str(target_dir)!r})\n",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            env=env,
            timeout=3600,
        )
        if result.returncode != 0:
            logger.error("%s download failed (rc=%d): %s", entry.id, result.returncode, (result.stderr or "")[-500:])
        return result.returncode == 0 and self.verify_local_model(entry)

    def _download_huggingface_snapshot(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror

        repo = entry.upstream_name
        if not repo:
            raise ValueError(f"model entry missing upstream_name: {entry.id}")

        target_dir = entry.resolved_install_dir()
        cmd = [
            sys.executable,
            "-c",
            "import os\n"
            "os.environ['PYTHONUTF8'] = '1'\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "from huggingface_hub import snapshot_download\n"
            f"snapshot_download(repo_id={repo!r}, local_dir={str(target_dir)!r})\n",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            env=env,
            timeout=3600,
        )
        if result.returncode != 0:
            logger.error("%s download failed (rc=%d): %s", entry.id, result.returncode, (result.stderr or "")[-500:])
        return result.returncode == 0 and self.verify_local_model(entry)

    # ── Async install with progress ──────────────────────────────────

    def install_with_progress(
        self,
        entry: ModelEntry,
        *,
        mirror: Optional[str] = None,
        force: bool = False,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """Install a model with real-time progress callback.

        Uses subprocess.Popen to stream stderr and parse huggingface_hub
        progress output. Calls on_progress(fraction, message) as download
        proceeds.
        """
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be installed: {entry.id}")
        if not entry.supports_install:
            raise ValueError(f"model cannot be installed: {entry.id}")

        status = self._status.resolve(entry)
        if status.status == ModelState.INSTALLED and not force:
            if on_progress:
                on_progress(1.0, "already installed")
            return True

        install_dir = entry.resolved_install_dir()
        install_dir.parent.mkdir(parents=True, exist_ok=True)

        strategy = entry.install_strategy
        cmd, env = self._build_download_cmd(entry, strategy, mirror)
        timeout = 600 if strategy == "whisper" else 3600

        if on_progress:
            on_progress(0.0, "starting download")

        success = self._run_with_progress(
            cmd, env, timeout, on_progress,
            cwd=str(self.project_root),
            monitor_dir=str(install_dir),
        )
        if not success:
            logger.error("%s download failed", entry.id)
            return False

        verified = self.verify_local_model(entry)
        if verified and on_progress:
            on_progress(1.0, "download complete")
        return verified

    def _build_download_cmd(
        self, entry: ModelEntry, strategy: str, mirror: Optional[str]
    ) -> tuple[list[str], dict[str, str]]:
        """Build the subprocess command and env for a download strategy."""
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror

        if strategy == "whisper":
            repo = WHISPER_REPOS[entry.id]
            target_dir = entry.resolved_install_dir()
            cmd = [
                sys.executable, "-c",
                "import os\n"
                "os.environ['PYTHONUTF8'] = '1'\n"
                "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
                f"from faster_whisper import download_model\n"
                f"download_model({repo!r}, output_dir={str(target_dir)!r})\n",
            ]
            return cmd, env

        if strategy == "qwen3":
            repo = QWEN3_REPOS[entry.id]
        elif strategy == "huggingface_snapshot":
            repo = entry.upstream_name
            if not repo:
                raise ValueError(f"model entry missing upstream_name: {entry.id}")
        else:
            raise ValueError(f"unsupported install strategy for progress: {strategy}")

        target_dir = entry.resolved_install_dir()
        cmd = [
            sys.executable, "-c",
            "import os\n"
            "os.environ['PYTHONUTF8'] = '1'\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "from huggingface_hub import snapshot_download\n"
            f"snapshot_download(repo_id={repo!r}, local_dir={str(target_dir)!r})\n",
        ]
        return cmd, env

    @staticmethod
    def _run_with_progress(
        cmd: list[str],
        env: dict[str, str],
        timeout: int,
        on_progress: Optional[Callable[[float, str], None]],
        cwd: str = ".",
        monitor_dir: str = "",
    ) -> bool:
        """Run a subprocess with directory-size-based progress monitoring."""
        try:
            proc = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
            )
        except OSError as exc:
            logger.error("failed to start subprocess: %s", exc)
            return False

        if on_progress and monitor_dir:
            def _monitor():
                monitor_path = Path(monitor_dir)
                while proc.poll() is None:
                    try:
                        if monitor_path.exists():
                            size = sum(f.stat().st_size for f in monitor_path.rglob("*") if f.is_file())
                            size_mb = size / (1024 * 1024)
                            on_progress(0.0, f"downloading... {size_mb:.0f} MB")
                    except (OSError, ValueError):
                        pass
                    time.sleep(2)

            threading.Thread(target=_monitor, daemon=True).start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.error("download timed out after %ds", timeout)
            return False

        return proc.returncode == 0
