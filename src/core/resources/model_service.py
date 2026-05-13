from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .model_catalog import DEFAULT_CATALOG_PATH, ModelCatalog, ModelEntry
from .model_installer import ModelInstaller
from .model_status import ModelStatus, ModelStatusResolver


class ModelService:
    def __init__(self, catalog_path: Path | None = None):
        self.catalog = ModelCatalog(catalog_path or DEFAULT_CATALOG_PATH)
        self.status_resolver = ModelStatusResolver()
        self.installer = ModelInstaller()

    def list_models(self, kind: str | None = None, category: str | None = None) -> List[ModelEntry]:
        return self.catalog.list(kind=kind, category=category)

    def get_model(self, model_id: str) -> ModelEntry:
        return self.catalog.get(model_id)

    def get_status(self, model_id: str) -> ModelStatus:
        return self.status_resolver.resolve(self.get_model(model_id))

    def get_all_statuses(self, kind: str | None = None, category: str | None = None) -> List[ModelStatus]:
        return [self.status_resolver.resolve(entry) for entry in self.list_models(kind=kind, category=category)]

    def verify(self, model_id: Optional[str] = None) -> Dict[str, bool]:
        entries = [self.get_model(model_id)] if model_id else [entry for entry in self.list_models() if entry.kind == "local"]
        return {entry.id: self.installer.verify_local_model(entry) for entry in entries if entry.kind == "local"}

    def install(self, model_id: str, mirror: str | None = None, force: bool = False) -> bool:
        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} 为云端模型，仅支持配置检查，不支持安装。")
        return self.installer.install_local_model(entry, mirror=mirror, force=force)

    def remove(self, model_id: str) -> None:
        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} 为云端模型，仅支持配置检查，不支持删除。")
        self.installer.remove_local_model(entry)

    def resolve_install_dir(self, model_id: str) -> Path:
        return self.get_model(model_id).resolved_install_dir()


_service: ModelService | None = None
_lock = threading.Lock()


def get_model_service() -> ModelService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ModelService()
    return _service
