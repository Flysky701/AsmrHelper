"""Read-only catalog for built-in pipeline presets."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT


class PresetCatalogService:
    """Load preset metadata without initializing pipeline execution services."""

    def __init__(self, presets_path: Path | str | None = None) -> None:
        self._presets_path = (
            Path(presets_path)
            if presets_path is not None
            else PROJECT_ROOT / "config" / "presets.yaml"
        )

    def list_presets(self) -> list[dict[str, Any]]:
        if not self._presets_path.exists():
            return []
        with self._presets_path.open(encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return data.get("presets", [])


_service: PresetCatalogService | None = None
_lock = threading.Lock()


def get_preset_catalog_service() -> PresetCatalogService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PresetCatalogService()
    return _service
