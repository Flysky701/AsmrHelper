from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .model_catalog import DEFAULT_CATALOG_PATH, ModelCatalog, ModelEntry
from .model_installer import ModelInstaller
from .model_status import ModelStatus, ModelStatusResolver

logger = logging.getLogger(__name__)


class ModelService:
    def __init__(self, catalog_path: Path | None = None):
        self.catalog = ModelCatalog(catalog_path or DEFAULT_CATALOG_PATH)
        self.status_resolver = ModelStatusResolver()
        self.installer = ModelInstaller()
        self._install_lock = threading.Lock()

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
        on_progress: Callable[[float, str], None] | None = None,
    ) -> bool:
        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} is a cloud model and cannot be installed")

        with self._install_lock:
            return self._install_entry(
                entry,
                mirror=mirror,
                force=force,
                install_mode=install_mode,
                install_dependencies=install_dependencies,
                install_recommended_assets=install_recommended_assets,
                allow_fallback_variant=allow_fallback_variant,
                on_progress=on_progress,
            )

    def _install_entry(
        self,
        entry: ModelEntry,
        *,
        mirror: str | None,
        force: bool,
        install_mode: str,
        install_dependencies: bool,
        install_recommended_assets: bool,
        allow_fallback_variant: bool,
        on_progress: Callable[[float, str], None] | None,
    ) -> bool:

        # Fail before a potentially large model download when its runtime
        # dependencies cannot be installed in the active environment.
        if install_dependencies:
            if on_progress:
                on_progress(0.0, "installing runtime dependencies")
            self._install_runtime_packages(entry)

        # Try installing the primary model
        success = self._install_with_fallback(
            entry,
            mirror=mirror,
            force=force,
            allow_fallback_variant=allow_fallback_variant,
            on_progress=on_progress,
        )

        if not success:
            return False

        # Install additional models/assets based on install_mode
        plan = self._resolve_install_plan(
            entry,
            install_mode=install_mode,
            install_recommended_assets=install_recommended_assets,
        )
        # Filter out the primary model (already installed above)
        remaining = [e for e in plan if e.id != entry.id]
        results = []
        for target in remaining:
            ok = self.installer.install_local_model(target, mirror=mirror, force=force)
            if not ok:
                logger.warning("failed to install dependency: %s", target.id)
            results.append(ok)
        return all(results)

    def remove(self, model_id: str) -> None:
        entry = self.get_model(model_id)
        if entry.kind == "cloud":
            raise ValueError(f"{model_id} is a cloud model and cannot be removed")
        self.installer.remove_local_model(entry)

    def resolve_install_dir(self, model_id: str) -> Path:
        return self.get_model(model_id).resolved_install_dir()

    def _install_with_fallback(
        self,
        entry: ModelEntry,
        *,
        mirror: str | None,
        force: bool,
        allow_fallback_variant: bool,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> bool:
        """Install model, optionally falling back to other variants in the same group."""
        install_fn = (
            (lambda e: self.installer.install_with_progress(e, mirror=mirror, force=force, on_progress=on_progress))
            if on_progress
            else (lambda e: self.installer.install_local_model(e, mirror=mirror, force=force))
        )

        if install_fn(entry):
            return True

        if not allow_fallback_variant or not entry.variant_group:
            return False

        # Find fallback variants in the same group (prefer primary variant)
        candidates = [
            e
            for e in self.list_models(kind="local", category=entry.category)
            if e.variant_group == entry.variant_group and e.id != entry.id
        ]
        # Sort: primary variants first, then by tier
        candidates.sort(key=lambda e: (not e.is_primary_variant, e.variant_tier or ""))

        for candidate in candidates:
            if install_fn(candidate):
                return True
        return False

    def _install_runtime_packages(self, entry: ModelEntry) -> None:
        """Install required runtime packages for a model.

        Resolution priority:
        1. required_python_extras: install via project extras
           (uses optional-dependencies groups from pyproject.toml — preferred)
        2. required_runtime_packages: direct pip install of explicit package list

        Both can be combined; extras are installed first, then explicit packages.
        Prefers uv if available, falls back to pip.
        """
        from src.config import PROJECT_ROOT

        extras = list(entry.required_python_extras)
        packages = list(entry.required_runtime_packages)

        if not extras and not packages:
            return

        installer = self._resolve_installer()

        # Install via project extras (preferred — resolves all transitive deps)
        if extras:
            try:
                logger.info("installing extras for %s: %s", entry.id, extras)
                cmd = installer["extras_cmd"](extras, str(PROJECT_ROOT))
                result = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=str(PROJECT_ROOT),
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "unknown error")[-500:]
                    raise RuntimeError(
                        f"failed to install optional dependency group "
                        f"{','.join(extras)} for {entry.id}: {detail}"
                    )
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    raise
                raise RuntimeError(
                    f"failed to install optional dependency group "
                    f"{','.join(extras)} for {entry.id}: {exc}"
                ) from exc

        # Install explicit packages (e.g. for models without project extras)
        if packages:
            try:
                logger.info("installing packages for %s: %s", entry.id, packages)
                cmd = installer["packages_cmd"](packages)
                result = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(PROJECT_ROOT),
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "unknown error")[-300:]
                    raise RuntimeError(
                        f"failed to install runtime packages for {entry.id}: {detail}"
                    )
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    raise
                raise RuntimeError(
                    f"failed to install runtime packages for {entry.id}: {exc}"
                ) from exc

    @staticmethod
    def _resolve_installer() -> dict:
        """Determine whether to use uv or pip for package installation.

        Returns dict with 'extras_cmd' and 'packages_cmd' callables that
        take (args, cwd) and (packages,) respectively, returning command lists.
        """
        import shutil

        uv_path = shutil.which("uv")
        if uv_path:
            return {
                "extras_cmd": lambda extras, cwd: [
                    uv_path, "pip", "install", "--python", sys.executable,
                    *[f"{cwd}[{','.join(extras)}]"],
                ],
                "packages_cmd": lambda packages: [
                    uv_path, "pip", "install", "--python", sys.executable, *packages,
                ],
            }

        return {
            "extras_cmd": lambda extras, cwd: [
                sys.executable, "-m", "pip", "install", "--quiet",
                "-e", f"{cwd}[{','.join(extras)}]",
            ],
            "packages_cmd": lambda packages: [
                sys.executable, "-m", "pip", "install", "--quiet", *packages,
            ],
        }

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
