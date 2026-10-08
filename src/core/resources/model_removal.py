"""Ownership evidence for app-installed weights; never adopt an existing directory."""
from functools import wraps
import json
from pathlib import Path
import os
import tempfile

MARKER = ".asmr-managed-weights.json"


def managed_path(entry):
    root = entry.resolved_install_root().absolute()
    path = entry.managed_install_dir().absolute()
    if path == root or not path.is_relative_to(root) or path.resolve() != entry.resolved_install_dir().resolve():
        raise ValueError("仅可删除应用管理的独立模型子目录；外部模型请解除引用")
    for current in (path, *path.parents):
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("模型路径包含链接或目录联接，不能删除")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("模型目录超出管理边界")
    return path


def inventory(path):
    files = []
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
            raise ValueError("模型包含链接或目录联接，不能删除")
        if not child.resolve().is_relative_to(path.resolve()):
            raise ValueError("模型文件超出管理目录")
        if child.is_file():
            stat = child.stat()
            files.append({"path": child.relative_to(path).as_posix(), "bytes": stat.st_size,
                          "modified_ns": stat.st_mtime_ns, "inode": stat.st_ino})
    return files


def removal_evidence(entry):
    if entry.kind != "local" or not entry.supports_remove:
        raise ValueError("此资源不支持删除本地权重")
    path = managed_path(entry)
    if not path.is_dir():
        raise ValueError("没有可删除的应用管理权重")
    files = inventory(path)
    marker = path / MARKER
    if not marker.is_file():
        raise ValueError("缺少应用安装所有权记录；保留现有权重，可手动管理或解除外部引用")
    ownership = json.loads(marker.read_text(encoding="utf-8"))
    if ownership.get("model_id") != entry.id or ownership.get("schema_version") != 1:
        raise ValueError("模型目录所有权记录不匹配")
    if {f["path"] for f in files} - {MARKER} != set(ownership.get("files", [])):
        raise ValueError("目录包含未登记或缺失文件，保留整个目录")
    return path, files


def track_owned_install(method):
    @wraps(method)
    def wrapped(self, entry, *args, **kwargs):
        # Only brand-new app directories can acquire ownership automatically.
        try:
            path = managed_path(entry)
            new = not path.exists()
            previous = json.loads((path / MARKER).read_text(encoding="utf-8")) if (path / MARKER).is_file() else {}
            owned = previous.get("model_id") == entry.id and previous.get("schema_version") == 1
            if owned:
                removal_evidence(entry)
        except (ValueError, OSError):
            path, new, owned = None, False, False
        result = method(self, entry, *args, **kwargs)
        if result and path is not None and (new or owned) and path.is_dir():
            files = inventory(path)
            payload = {"schema_version": 1, "model_id": entry.id,
                       "files": [f["path"] for f in files if f["path"] != MARKER]}
            fd, name = tempfile.mkstemp(dir=path, prefix=".ownership-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream); stream.flush(); os.fsync(stream.fileno())
                os.replace(name, path / MARKER)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return result
    return wrapped
