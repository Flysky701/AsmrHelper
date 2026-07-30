"""Resolve catalog model ids to installed paths or upstream references."""

from __future__ import annotations

from .model_catalog import DEFAULT_CATALOG_PATH, ModelCatalog, ModelCatalogError

_catalog = ModelCatalog(DEFAULT_CATALOG_PATH)


def resolve_model_reference(model_id: str) -> str:
    """Prefer the managed local model directory, then the upstream model id."""
    if not model_id:
        return model_id

    try:
        entry = _catalog.get(model_id)
    except ModelCatalogError:
        return model_id

    install_dir = entry.resolved_install_dir()
    if install_dir.exists():
        return str(install_dir)
    return entry.upstream_name or model_id
