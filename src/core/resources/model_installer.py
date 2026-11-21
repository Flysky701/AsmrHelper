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

from src.config import APP_ROOT, PROJECT_ROOT
from src.workspace_paths import freeze_directories

from .download_sources import (
    HF_MIRROR,
    HUGGINGFACE,
    DownloadSource,
    is_domestic_download_mode,
    model_sources,
    recoverable_source_error,
    resolve_demucs_base_urls,
    resolve_download_sources,
    resolve_modelscope_repo,
)
from .model_catalog import ModelEntry
from .model_removal import removal_evidence, track_owned_install
from .model_status import ModelStatusResolver

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


class ModelDownloadError(RuntimeError):
    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class ModelInstaller:
    @staticmethod
    def _guard_shared(entry):
        from .model_assets import shared
        if shared(entry):
            raise ValueError('共享模型为只读，不能覆盖或删除；请解除引用或使用本项目管理的模型目录')

    @staticmethod
    def _reuse_shared(entry, force):
        from .model_assets import complete, shared
        if not shared(entry):
            return False
        if not force and complete(entry, entry.resolved_install_dir()):
            return True
        ModelInstaller._guard_shared(entry)
        return False

    @staticmethod
    def _weights_present(entry):
        from .model_assets import complete
        return complete(entry, entry.resolved_install_dir())

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or PROJECT_ROOT
        self._status = ModelStatusResolver()

    def verify_local_model(self, entry: ModelEntry) -> bool:
        from .model_assets import complete
        return complete(entry, entry.resolved_install_dir())

    def remove_local_model(self, entry: ModelEntry) -> None:
        self._guard_shared(entry)
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be removed: {entry.id}")
        if not entry.supports_remove:
            raise ValueError(f"model cannot be removed: {entry.id}")

        install_dir, _ = removal_evidence(entry)
        shutil.rmtree(install_dir)

    @freeze_directories
    @track_owned_install
    def install_local_model(self, entry: ModelEntry, mirror: Optional[str] = None, force: bool = False) -> bool:
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be installed: {entry.id}")
        if not entry.supports_install:
            raise ValueError(f"model cannot be installed: {entry.id}")

        if self._reuse_shared(entry, force):
            return True
        if self._weights_present(entry) and not force:
            return True

        install_dir = entry.resolved_install_dir()
        install_dir.parent.mkdir(parents=True, exist_ok=True)

        strategy = entry.install_strategy
        if strategy == "release_files":
            return self._download_release_files(entry, force=force)
        if strategy == "whisper":
            return self._download_whisper(entry, mirror)
        if strategy == "qwen3":
            return self._download_qwen3(entry, mirror)
        if strategy == "huggingface_snapshot":
            return self._download_huggingface_snapshot(entry, mirror)
        if strategy == "package":
            return self._download_demucs(entry, mirror=mirror) if entry.provider == "demucs" else self.verify_local_model(entry)
        raise ValueError(f"unknown install strategy: {strategy}")

    def _download_release_files(self, entry, on_progress=None, *, force=False):
        from tempfile import NamedTemporaryFile
        from urllib.request import urlopen

        self._guard_shared(entry)
        directory = entry.resolved_install_dir()
        directory.mkdir(parents=True, exist_ok=True)
        sources = {source.get("directory", ""): source["endpoint"].rstrip("/") for source in entry.download_sources}
        for index, name in enumerate(entry.required_files):
            target = directory / name
            if not force and target.is_file() and target.stat().st_size:
                continue
            if on_progress:
                on_progress(index / len(entry.required_files), f"下载 {name}")
            directory_name, _, filename = name.rpartition("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            url = sources[directory_name] + "/" + filename if directory_name in sources else sources[""] + "/" + name
            with urlopen(url, timeout=90) as response:
                with NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    pending = Path(stream.name)
                try:
                    with pending.open("wb") as stream:
                        shutil.copyfileobj(response, stream)
                    length = response.headers.get("Content-Length")
                    if not pending.stat().st_size or (length and pending.stat().st_size != int(length)):
                        raise ModelDownloadError(f"下载不完整：{name}")
                    pending.replace(target)
                finally:
                    pending.unlink(missing_ok=True)
        return self.verify_local_model(entry)

    def _download_whisper(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        return self.install_with_progress(entry, mirror=mirror, force=True)

    def _download_demucs(
        self,
        entry,
        on_progress=None,
        mirror: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
    ):
        import hashlib
        from urllib.request import urlopen

        from .model_assets import DEMUCS_FILES

        self._guard_shared(entry)
        target = entry.resolved_install_dir()
        target.mkdir(parents=True, exist_ok=True)
        files = DEMUCS_FILES[entry.upstream_name or 'htdemucs']
        base_urls = resolve_demucs_base_urls(
            mirror,
            base_url=base_url,
            download_sources_meta=getattr(entry, 'download_sources', None),
        )
        for index, name in enumerate(files):
            path = target / name
            if path.is_file() and path.stat().st_size:
                continue
            if on_progress:
                on_progress(index / len(files), f'下载缺失权重 {name}')
            pending = path.with_suffix('.partial')
            last_exc: Exception | None = None
            for attempt, candidate_base in enumerate(base_urls, 1):
                digest = hashlib.sha256()
                url = candidate_base.rstrip('/') + '/' + name
                try:
                    with urlopen(url, timeout=60) as response, pending.open('wb') as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                    if not digest.hexdigest().startswith(name.split('-')[1].split('.')[0]):
                        raise ModelDownloadError(f'权重校验失败：{name}')
                    pending.replace(path)
                    last_exc = None
                    break
                except ModelDownloadError:
                    pending.unlink(missing_ok=True)
                    raise
                except Exception as exc:
                    pending.unlink(missing_ok=True)
                    last_exc = exc
                    if attempt >= len(base_urls) or not recoverable_source_error(str(exc)):
                        raise ModelDownloadError(f'Demucs 权重下载失败 ({url}): {exc}') from exc
                    logger.warning(
                        'Demucs download failed from %s (%s); falling back to %s',
                        candidate_base,
                        type(exc).__name__,
                        base_urls[attempt],
                    )
            if last_exc is not None:
                raise ModelDownloadError(f'Demucs 权重下载失败：{name}: {last_exc}') from last_exc
        return True

    def _resolve_strategy_hf_repo(self, entry: ModelEntry, strategy: str) -> str:
        if strategy == "whisper":
            return WHISPER_REPOS[entry.id]
        if strategy == "qwen3":
            return QWEN3_REPOS[entry.id]
        if strategy == "huggingface_snapshot":
            if not entry.upstream_name:
                raise ValueError(f"model entry missing upstream_name: {entry.id}")
            return entry.upstream_name
        raise ValueError(f"unsupported install strategy for progress: {strategy}")

    def _resolve_entry_sources(
        self, entry: ModelEntry, strategy: str, mirror: Optional[str]
    ) -> list[DownloadSource]:
        hf_repo = self._resolve_strategy_hf_repo(entry, strategy)
        return resolve_download_sources(entry, mirror=mirror, hf_repo=hf_repo)

    def _download_snapshot_tiers(
        self, entry: ModelEntry, strategy: str, mirror: Optional[str]
    ) -> bool:
        sources = self._resolve_entry_sources(entry, strategy, mirror)
        for attempt, source in enumerate(sources, 1):
            cmd, env = self._build_source_cmd(entry, strategy, source, raw_mirror=mirror)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                env=env,
                timeout=3600,
            )
            if result.returncode == 0 and self.verify_local_model(entry):
                return True
            detail = (result.stderr or result.stdout or "")[-500:]
            if attempt < len(sources) and recoverable_source_error(detail):
                logger.warning(
                    "%s download failed on %s (rc=%d); falling back to %s: %s",
                    entry.id,
                    source.endpoint,
                    result.returncode,
                    sources[attempt].endpoint,
                    detail,
                )
                continue
            logger.error("%s download failed (rc=%d): %s", entry.id, result.returncode, detail)
            break
        return False

    def _download_qwen3(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        return self._download_snapshot_tiers(entry, "qwen3", mirror)

    def _download_huggingface_snapshot(self, entry: ModelEntry, mirror: Optional[str]) -> bool:
        return self._download_snapshot_tiers(entry, entry.install_strategy, mirror)

    # ── Async install with progress ──────────────────────────────────

    @freeze_directories
    @track_owned_install
    def install_with_progress(
        self,
        entry: ModelEntry,
        *,
        mirror: Optional[str] = None,
        force: bool = False,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """Install a model with real-time progress callback and 3-tier fallback."""
        if entry.kind != "local":
            raise ValueError(f"cloud models cannot be installed: {entry.id}")
        if not entry.supports_install:
            raise ValueError(f"model cannot be installed: {entry.id}")

        strategy = entry.install_strategy
        if strategy == "release_files":
            if self._reuse_shared(entry, force):
                return True
            return self._download_release_files(entry, on_progress, force=force)
        if strategy == "package":
            if self._reuse_shared(entry, force):
                return True
            installed = self.verify_local_model(entry)
            if entry.provider == "demucs" and (force or not installed):
                installed = self._download_demucs(entry, on_progress, mirror=mirror)
            if on_progress:
                on_progress(
                    1.0 if installed else 0.0,
                    ("weights available" if installed else "weights unavailable") if entry.provider == "demucs"
                    else ("runtime packages installed" if installed else "runtime packages unavailable"),
                )
            return installed

        if self._reuse_shared(entry, force):
            return True
        if self._weights_present(entry) and not force:
            if on_progress:
                on_progress(1.0, "already installed")
            return True

        install_dir = entry.resolved_install_dir()
        install_dir.parent.mkdir(parents=True, exist_ok=True)

        timeout = 600 if strategy == "whisper" else 3600
        if on_progress:
            on_progress(0.0, "starting download")

        if strategy == "whisper":
            cmd, env = self._build_download_cmd(entry, strategy, mirror)
            success = self._run_with_progress(
                cmd,
                env,
                timeout,
                on_progress,
                cwd=str(self.project_root),
                monitor_dir=str(install_dir),
            )
        else:
            sources = self._resolve_entry_sources(entry, strategy, mirror)
            domestic = is_domestic_download_mode(mirror)
            if domestic:
                attempt_plan = list(sources)
            elif len(sources) >= 2:
                attempt_plan = [sources[0], sources[0], sources[1]]
            else:
                attempt_plan = [sources[0], sources[0], sources[0]]

            success = False
            max_attempts = len(attempt_plan)
            for attempt, source in enumerate(attempt_plan, 1):
                cmd, env = self._build_source_cmd(entry, strategy, source, raw_mirror=mirror)
                try:
                    success = self._run_with_progress(
                        cmd,
                        env,
                        timeout,
                        on_progress,
                        cwd=str(self.project_root),
                        monitor_dir=str(install_dir),
                    )
                    if success:
                        break
                except ModelDownloadError as exc:
                    if attempt >= max_attempts or not recoverable_source_error(exc.detail or str(exc)):
                        raise
                    next_source = attempt_plan[attempt]
                    if on_progress:
                        if domestic and next_source.endpoint != source.endpoint:
                            on_progress(
                                0.0,
                                f"source {source.type} failed; falling back to {next_source.type} ({attempt + 1}/{max_attempts})",
                            )
                        else:
                            on_progress(
                                0.0,
                                f"download interrupted; resuming attempt {attempt + 1}/{max_attempts}",
                            )
                    time.sleep(min(attempt * 2, 5))

        if not success:
            logger.error("%s download failed", entry.id)
            return False

        verified = self.verify_local_model(entry)
        if verified and on_progress:
            on_progress(1.0, "download complete")
        return verified

    def _build_source_cmd(
        self,
        entry: ModelEntry,
        strategy: str,
        source: DownloadSource,
        *,
        raw_mirror: Optional[str] = None,
    ) -> tuple[list[str], dict[str, str]]:
        target_dir = entry.resolved_install_dir()
        if source.type == "modelscope":
            env = self._build_download_env(None)
            env.pop("HF_ENDPOINT", None)
            cmd = [
                sys.executable,
                "-c",
                "import os\n"
                "os.environ['PYTHONUTF8'] = '1'\n"
                "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
                "from src.core.resources.download_sources import download_modelscope_snapshot\n"
                f"download_modelscope_snapshot({source.repo_id!r}, {str(target_dir)!r}, "
                f"revision={source.revision!r}, endpoint={source.endpoint!r}, "
                f"required_files={list(entry.required_files)!r}, "
                f"required_dirs={list(entry.required_dirs)!r})\n",
            ]
            return cmd, env

        effective_mirror = raw_mirror if source.type == "custom" and raw_mirror else source.endpoint
        if raw_mirror is None and source.type == "huggingface" and not os.environ.get("HF_ENDPOINT"):
            env = self._build_download_env(None)
        else:
            env = self._build_download_env(effective_mirror)

        cmd = [
            sys.executable,
            "-c",
            "import os\n"
            "os.environ['PYTHONUTF8'] = '1'\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "from huggingface_hub import snapshot_download\n"
            f"snapshot_download(repo_id={source.repo_id!r}, local_dir={str(target_dir)!r}, max_workers=1)\n",
        ]
        return cmd, env

    def _build_download_cmd(
        self, entry: ModelEntry, strategy: str, mirror: Optional[str]
    ) -> tuple[list[str], dict[str, str]]:
        """Build the primary subprocess command and env for a download strategy."""
        if strategy == "whisper":
            repo = self._resolve_strategy_hf_repo(entry, strategy)
            # Validate before starting any process, including inherited HF_ENDPOINT.
            model_sources(mirror, repo=repo)
            env = self._build_download_env(mirror)
            env["HF_HUB_ETAG_TIMEOUT"] = "15"
            env["HF_HUB_DOWNLOAD_TIMEOUT"] = "30"
            env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
            env["HF_HUB_DISABLE_XET"] = "1"
            ms_repo, _ = resolve_modelscope_repo(entry)
            target_dir = entry.resolved_install_dir()
            cmd = [
                sys.executable,
                "-c",
                "import logging; logging.basicConfig(level=logging.INFO)\n"
                "from src.core.resources.whisper_download import download\n"
                f"download({repo!r}, {str(target_dir)!r}, {mirror!r}, modelscope_repo={ms_repo!r})\n",
            ]
            return cmd, env

        sources = self._resolve_entry_sources(entry, strategy, mirror)
        return self._build_source_cmd(entry, strategy, sources[0], raw_mirror=mirror)

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
            raise ModelDownloadError(f"failed to start model download: {exc}") from exc

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
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.communicate()
            raise ModelDownloadError(
                f"model download timed out after {timeout} seconds"
            ) from exc

        if proc.returncode != 0:
            detail = (stderr or stdout or "no subprocess output").strip()[-2000:]
            summary = next(
                (line.strip() for line in reversed(detail.splitlines()) if line.strip()),
                "no subprocess output",
            )
            raise ModelDownloadError(
                f"model download failed (exit code {proc.returncode}): {summary}",
                detail=detail,
            )
        if "whisper_download" in cmd[-1]:
            logger.info("FasterWhisper download log: %s", (stderr or stdout or "")[-3000:])
        return proc.returncode == 0

    @staticmethod
    def _build_download_env(mirror: Optional[str]) -> dict[str, str]:
        from src.core.runtime.profiles import get_runtime_profile_resolver

        env = get_runtime_profile_resolver().subprocess_env()
        app_root_str = str(APP_ROOT)
        existing_py_path = env.get("PYTHONPATH", "")
        py_parts = [p for p in existing_py_path.split(os.pathsep) if p]
        if app_root_str not in py_parts:
            env["PYTHONPATH"] = os.pathsep.join([app_root_str, *py_parts])

        if mirror:
            raw = mirror.strip()
            normalized = raw.lower().rstrip("/")
            if is_domestic_download_mode(raw):
                env["ASMR_HELPER_DOWNLOAD_REGION"] = "cn"
                env["HF_ENDPOINT"] = HF_MIRROR
            elif normalized == "hf-mirror":
                env["HF_ENDPOINT"] = HF_MIRROR
            elif normalized == "huggingface":
                env["HF_ENDPOINT"] = HUGGINGFACE
            else:
                env["HF_ENDPOINT"] = raw

        env.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
        env.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
        return env
