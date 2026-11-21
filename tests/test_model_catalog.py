from __future__ import annotations



from src.core.resources.model_catalog import DEFAULT_CATALOG_PATH, load_catalog_file


def test_project_catalog_declares_size_for_every_local_model():
    catalog = load_catalog_file(DEFAULT_CATALOG_PATH)
    local_models = catalog.list(kind="local")

    assert local_models
    assert all(entry.estimated_size_mb and entry.estimated_size_mb > 0 for entry in local_models)
