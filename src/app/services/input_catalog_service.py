"""Input asset inspection and companion discovery service."""

from __future__ import annotations

import threading
from src.core.sessions import InputAsset, InputCatalog


class InputCatalogService:
    """Inspect local inputs and discover companion assets."""

    def __init__(self) -> None:
        self._catalog = InputCatalog()
        self._lock = threading.Lock()

    def inspect_paths(self, paths: list[str]) -> list[InputAsset]:
        with self._lock:
            return self._catalog.inspect_paths(paths)

    def get_asset(self, asset_id: str) -> InputAsset:
        with self._lock:
            return self._catalog.get_asset(asset_id)

    def discover_companions(self, asset_id: str) -> list[InputAsset]:
        with self._lock:
            return self._catalog.discover_companions(asset_id)


_service: InputCatalogService | None = None
_lock = threading.Lock()


def get_input_catalog_service() -> InputCatalogService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = InputCatalogService()
    return _service
