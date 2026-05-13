from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from src.config import PROJECT_ROOT

from .model_catalog import ModelEntry
from .model_status import ModelState, ModelStatusResolver


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
            raise ValueError(f"云端模型不支持删除: {entry.id}")
        if not entry.supports_remove:
            raise ValueError(f"模型不支持删除: {entry.id}")

        install_dir = entry.resolved_install_dir()
        if install_dir.exists():
            shutil.rmtree(install_dir)

    def install_local_model(self, entry: ModelEntry, mirror: Optional[str] = None, force: bool = False) -> bool:
        if entry.kind != "local":
            raise ValueError(f"云端模型不支持安装: {entry.id}")
        if not entry.supports_install:
            raise ValueError(f"模型不支持安装: {entry.id}")

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
        raise ValueError(f"未知安装策略: {strategy}")

    def _download_whisper(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror

        repo = WHISPER_REPOS[entry.id]
        target_dir = entry.resolved_install_dir()
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
        return result.returncode == 0 and self.verify_local_model(entry)

    def _download_qwen3(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        env = os.environ.copy()
        if mirror:
            env["HF_ENDPOINT"] = mirror
            os.environ["HF_ENDPOINT"] = mirror

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
        return result.returncode == 0 and self.verify_local_model(entry)
