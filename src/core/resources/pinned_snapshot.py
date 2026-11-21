"""Install a known Hugging Face snapshot with offline file identities."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from .download_sources import recoverable_source_error

CHUNK_SIZE = 8 * 1024 * 1024


def has_expected_size(path: Path, size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def _digest(size: int, expected: str):
    if len(expected) == 64:
        return hashlib.sha256()
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    return digest


def _verified(path: Path, size: int, expected: str) -> bool:
    if not has_expected_size(path, size):
        return False
    digest = _digest(size, expected)
    with path.open("rb") as stream:
        while block := stream.read(CHUNK_SIZE):
            digest.update(block)
    return digest.hexdigest() == expected


def _copy_file(client, url, target, size, expected, report, *, force):
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".asmr-snapshot-", suffix=".part")
    pending = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream, client.stream("GET", url) as response:
            response.raise_for_status()
            digest = _digest(size, expected)
            written = 0
            last_update = time.monotonic()
            for block in response.iter_bytes(CHUNK_SIZE):
                written += len(block)
                if written > size:
                    raise ValueError(f"下载超过官方文件大小：{target.name}")
                digest.update(block)
                stream.write(block)
                if time.monotonic() - last_update >= 2:
                    report(written)
                    last_update = time.monotonic()
            if written != size or digest.hexdigest() != expected:
                raise ValueError(f"下载文件大小或哈希与固定版本不符：{target.name}")
            stream.flush()
            os.fsync(stream.fileno())
        report(written)
        if target.is_symlink() or (target.exists() and not force):
            if not target.is_symlink() and _verified(target, size, expected):
                return
            raise ValueError(f"发布前发现现有模型文件冲突：{target}")
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)


def install_snapshot(entry, directory, sources, *, force=False, on_progress=None, readonly=False):
    total = sum(size for size, _ in entry.snapshot_files.values())
    completed = 0
    missing = {}
    for name, (size, expected) in entry.snapshot_files.items():
        target = directory / name
        if on_progress:
            on_progress(completed / total, f"检查 {name}")
        if _verified(target, size, expected):
            completed += size
            continue
        if readonly or target.is_symlink() or (target.exists() and not (force and target.is_file())):
            raise ValueError(f"现有模型文件与固定版本不符，请检查文件或显式重装：{target}")
        missing[name] = (size, expected)

    if not missing:
        if on_progress:
            on_progress(1.0, "已校验全部模型文件")
        return
    remaining = total - completed
    volume = next(path for path in (directory, *directory.parents) if path.exists())
    free = shutil.disk_usage(volume).free
    if remaining > free:
        raise ValueError(f"模型磁盘空间不足：仍需 {remaining / 1e9:.2f} GB，当前可用 {free / 1e9:.2f} GB")
    directory.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120, connect=15)) as client:
        for name, (size, expected) in missing.items():
            def report(written):
                if on_progress:
                    on_progress((completed + written) / total, f"下载 {name}")

            report(0)
            for index, source in enumerate(sources):
                url = f"{source.endpoint}/{source.repo_id}/resolve/{entry.snapshot_revision}/{quote(name, safe='')}"
                try:
                    _copy_file(client, url, directory / name, size, expected, report, force=force)
                    break
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if index + 1 == len(sources) or not recoverable_source_error(str(exc)):
                        raise
            completed += size
    if on_progress:
        on_progress(1.0, "已校验全部模型文件")
