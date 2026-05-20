"""Input asset inspection and companion discovery service."""

from __future__ import annotations

import threading
from pathlib import Path

from src.utils import find_subtitle_file

from ..dto import InputAsset

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
_SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".lrc"}
_SCRIPT_EXTENSIONS = {".txt", ".md", ".pdf"}


class InputCatalogService:
    """Inspect local inputs and discover companion assets."""

    def __init__(self) -> None:
        self._assets: dict[str, InputAsset] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def inspect_paths(self, paths: list[str]) -> list[InputAsset]:
        assets: list[InputAsset] = []
        for raw_path in paths:
            asset = self._build_asset(raw_path)
            with self._lock:
                existing = self._assets.get(asset.absolute_path.lower())
                if existing is not None:
                    assets.append(existing)
                else:
                    self._assets[asset.absolute_path.lower()] = asset
                    assets.append(asset)
        return [self._clone(asset) for asset in assets]

    def get_asset(self, asset_id: str) -> InputAsset:
        with self._lock:
            for asset in self._assets.values():
                if asset.asset_id == asset_id:
                    return self._clone(asset)
        raise ValueError(f"unknown asset id: {asset_id}")

    def discover_companions(self, asset_id: str) -> list[InputAsset]:
        asset = self.get_asset(asset_id)
        path = Path(asset.absolute_path)
        discovered: list[InputAsset] = []

        if asset.kind == "audio" and path.exists():
            subtitle_path = find_subtitle_file(path)
            if subtitle_path is not None:
                discovered.extend(self.inspect_paths([str(subtitle_path)]))

        return discovered

    def _build_asset(self, raw_path: str) -> InputAsset:
        path = Path(raw_path).expanduser()
        try:
            absolute = str(path.resolve(strict=False))
        except Exception:
            absolute = str(path)
        extension = path.suffix.lower()
        kind = self._detect_kind(path, extension)
        exists = path.exists()
        readable = exists
        size_bytes = path.stat().st_size if exists and path.is_file() else 0
        warnings: list[str] = []

        if not exists:
            warnings.append("path_not_found")
        elif path.is_dir():
            readable = True
        else:
            try:
                with open(path, "rb"):
                    pass
            except OSError:
                readable = False
                warnings.append("path_not_readable")

        with self._lock:
            self._counter += 1
            asset_id = f"asset-{self._counter}"

        return InputAsset(
            asset_id=asset_id,
            absolute_path=absolute,
            kind=kind,
            display_name=path.name,
            extension=extension,
            exists=exists,
            readable=readable,
            size_bytes=size_bytes,
            warnings=warnings,
        )

    def _detect_kind(self, path: Path, extension: str) -> str:
        if path.is_dir():
            return "folder"
        if extension in _AUDIO_EXTENSIONS:
            return "audio"
        if extension in _SUBTITLE_EXTENSIONS:
            return "subtitle"
        if extension in _SCRIPT_EXTENSIONS:
            return "script"
        return "unknown"

    def _clone(self, asset: InputAsset) -> InputAsset:
        return InputAsset(
            asset_id=asset.asset_id,
            absolute_path=asset.absolute_path,
            kind=asset.kind,
            display_name=asset.display_name,
            extension=asset.extension,
            exists=asset.exists,
            readable=asset.readable,
            size_bytes=asset.size_bytes,
            warnings=list(asset.warnings),
            related_assets=list(asset.related_assets),
        )


_service: InputCatalogService | None = None
_lock = threading.Lock()


def get_input_catalog_service() -> InputCatalogService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = InputCatalogService()
    return _service
