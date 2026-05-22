from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config import config

from .model_catalog import ModelEntry


class ModelState:
    MISSING = "missing"
    INVALID = "invalid"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"


@dataclass(frozen=True)
class ModelStatus:
    model_id: str
    status: str
    detail: str = ""
    path: Optional[Path] = None


class ModelStatusResolver:
    def resolve(self, entry: ModelEntry) -> ModelStatus:
        if entry.kind == "cloud":
            api_key = config.get(entry.api_key_config or "", "")
            if api_key:
                return ModelStatus(entry.id, ModelState.CONFIGURED, "API key configured")
            return ModelStatus(entry.id, ModelState.UNCONFIGURED, "API key missing")

        if entry.install_strategy == "package":
            try:
                __import__(entry.provider or "")
                return ModelStatus(entry.id, ModelState.INSTALLED, "Package import available")
            except Exception:
                return ModelStatus(entry.id, ModelState.MISSING, "Package import unavailable")

        install_dir = entry.resolved_install_dir()
        if not install_dir.exists():
            return ModelStatus(entry.id, ModelState.MISSING, "Install directory missing", install_dir)

        for required_dir in entry.required_dirs:
            if not (install_dir / required_dir).exists():
                return ModelStatus(entry.id, ModelState.INVALID, f"Missing dir: {required_dir}", install_dir)

        for required_file in entry.required_files:
            if not self._has_required_file(install_dir, required_file):
                return ModelStatus(entry.id, ModelState.INVALID, f"Missing file: {required_file}", install_dir)

        return ModelStatus(entry.id, ModelState.INSTALLED, "Model files verified", install_dir)

    @staticmethod
    def _has_required_file(install_dir: Path, required_file: str) -> bool:
        if (install_dir / required_file).exists():
            return True
        # Strict: match by exact filename, not substring
        return any(p.name == required_file for p in install_dir.rglob("*") if p.name == required_file)
