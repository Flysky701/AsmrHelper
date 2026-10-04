"""Shared resolution of configured workspace directories (without creating them)."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from src.config import PROJECT_ROOT, config


_directories = ContextVar("workspace_directories", default=None)


def resolve_directory(value, default: str | Path, *, project_root: Path | None = None) -> Path:
    root = project_root or PROJECT_ROOT
    path = Path(value or default).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    # Do not require a machine-wide long-path policy for user-selected folders.
    text = str(path)
    if os.name == 'nt' and len(text) >= 248 and not text.startswith('\\\\?\\'):
        path = Path('\\\\?\\UNC\\' + text[2:] if text.startswith('\\\\') else '\\\\?\\' + text)
    return path


def model_directory(default: str | Path = 'models', *, project_root: Path | None = None) -> Path:
    snapshot = _directories.get()
    if snapshot is not None:
        return Path(snapshot["models"])
    # Preserve the explicit deployment override, then the user's saved setting.
    value = os.getenv('ASMR_HELPER_MODEL_ROOT') or config.get('paths.model_cache_dir', '')
    return resolve_directory(value, default, project_root=project_root)


def path_setting_errors(paths: dict) -> list[str]:
    if not isinstance(paths, dict):
        return ['目录设置必须是对象']
    labels = {'output_dir': '输出目录', 'vtt_dir': 'VTT 字幕目录',
              'model_cache_dir': '模型缓存目录', 'temp_dir': '临时文件目录'}
    errors = []
    for key, value in paths.items():
        if key not in labels:
            continue
        if not isinstance(value, str):
            errors.append(f'{labels[key]}必须是路径字符串，留空可恢复默认位置')
            continue
        if not value:
            continue
        try:
            raw = Path(value)
            if os.name == 'nt' and (raw.is_reserved() or any(
                any(ch in part for ch in '<>"|?*') or part.endswith((' ', '.'))
                for part in raw.parts if part not in (raw.anchor, '.', '..')
            )):
                raise ValueError('路径含 Windows 不支持的名称或字符')
            path = resolve_directory(value, '.')
            parent = path
            while not parent.exists():
                if parent.parent == parent:
                    raise ValueError('盘符或共享位置不存在')
                parent = parent.parent
            if not parent.is_dir():
                raise ValueError('路径或上级路径指向文件，必须选择目录')
            # Probe only the existing parent; validation must not create the chosen
            # directory or move files. Windows os.access does not reliably test ACLs.
            with tempfile.TemporaryFile(prefix='.asmr-write-check-', dir=parent):
                pass
        except (OSError, ValueError) as exc:
            detail = str(exc) if isinstance(exc, ValueError) else '无法访问或写入此位置，请检查权限、磁盘及路径'
            errors.append(f'{labels[key]}：{detail}')
    return errors


def temporary_directory(*, project_root: Path | None = None) -> Path:
    snapshot = _directories.get()
    if snapshot is not None:
        return Path(snapshot["temp"])
    value = os.getenv("ASMR_HELPER_TEMP_ROOT") or config.get("paths.temp_dir", "")
    return resolve_directory(value, "debug/runtime", project_root=project_root)


@contextmanager
def directory_context(*, temp_root: str | Path | None = None, model_root: str | Path | None = None):
    snapshot = {"models": str(model_root or model_directory()), "temp": str(temp_root or temporary_directory())}
    token = _directories.set(snapshot)
    try:
        yield
    finally:
        _directories.reset(token)


def freeze_directories(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with directory_context():
            return function(*args, **kwargs)
    return wrapped
