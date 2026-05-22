from __future__ import annotations

import threading
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

    def install(
        self,
        model_id: str,
        mirror: str | None = None,
        force: bool = False,
        install_mode: str = "single",
        install_dependencies: bool = True,
        install_recommended_assets: bool = False,
        allow_fallback_variant: bool = False,
    ) -> bool:
        del install_dependencies, allow_fallback_variant

        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} is a cloud model and cannot be installed")

        plan = self._resolve_install_plan(
            entry,
            install_mode=install_mode,
            install_recommended_assets=install_recommended_assets,
        )
        return all(self.installer.install_local_model(target, mirror=mirror, force=force) for target in plan)

    def remove(self, model_id: str) -> None:
        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} is a cloud model and cannot be removed")
        self.installer.remove_local_model(entry)

    def resolve_install_dir(self, model_id: str) -> Path:
        return self.get_model(model_id).resolved_install_dir()

    def _resolve_install_plan(
        self,
        entry: ModelEntry,
        *,
        install_mode: str,
        install_recommended_assets: bool,
    ) -> List[ModelEntry]:
        if install_mode not in {"single", "recommended", "family_all"}:
            raise ValueError(f"unsupported install mode: {install_mode}")

        include_recommended = install_recommended_assets or install_mode == "recommended"
        target_ids: list[str] = []

        def add_model_with_assets(model: ModelEntry) -> None:
            target_ids.append(model.id)
            target_ids.extend(model.required_assets)
            if include_recommended:
                target_ids.extend(model.recommended_assets)

        if install_mode == "family_all" and entry.family_id:
            family_entries = [
                candidate
                for candidate in self.list_models(kind="local", category=entry.category)
                if candidate.family_id == entry.family_id
            ]
            for candidate in family_entries:
                add_model_with_assets(candidate)
        else:
            add_model_with_assets(entry)

        ordered_ids = list(dict.fromkeys(target_ids))
        return [self.get_model(current_id) for current_id in ordered_ids]


_service: ModelService | None = None
_lock = threading.Lock()


def get_model_service() -> ModelService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ModelService()
    return _service
