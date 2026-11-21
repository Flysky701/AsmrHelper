from __future__ import annotations

from typing import Any

from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.core.resources.model_catalog import ModelCatalog, ModelEntry


def _backend(entry: ModelEntry) -> str:
    return entry.provider or entry.engine or ""


def _descriptors() -> dict[tuple[str, str], dict[str, Any]]:
    items = CapabilityDescriptorService().list_descriptors()
    return {(item["category"], item["provider"]): item for item in items}


def test_each_catalog_entry_has_a_capability_provider() -> None:
    descriptors = _descriptors()

    for entry in ModelCatalog().list():
        key = (entry.category, _backend(entry))
        assert key in descriptors, (
            f"model {entry.id!r} references capability provider "
            f"{entry.category}/{_backend(entry) or '<empty>'}, but no descriptor exists"
        )


def test_each_local_capability_model_has_an_explicit_resource_mapping() -> None:
    catalog_entries = ModelCatalog().list(kind="local")

    for descriptor in _descriptors().values():
        if descriptor["kind"] != "local":
            continue
        matching_entries = [
            entry
            for entry in catalog_entries
            if entry.category == descriptor["category"]
            and (
                _backend(entry) == descriptor["provider"]
                or (
                    entry.category == "separator"
                    and descriptor["provider"] == "demucs"
                    and _backend(entry) == "audio_separator"
                )
            )
        ]
        covered_models = {
            model_id
            for entry in matching_entries
            for model_id in (entry.capability_models or [entry.id])
        }
        missing = set(descriptor["supported_models"]) - covered_models
        assert not missing, (
            f"capability {descriptor['category']}/{descriptor['provider']} "
            f"has models without config/models.yaml resource mappings: {sorted(missing)}"
        )


def test_local_catalog_mappings_are_advertised_by_the_capability() -> None:
    descriptors = _descriptors()

    for entry in ModelCatalog().list(kind="local"):
        descriptor = descriptors[(entry.category, _backend(entry))]
        mapped_models = set(entry.capability_models or [entry.id])
        unknown = mapped_models - set(descriptor["supported_models"])
        assert not unknown, (
            f"model resource {entry.id!r} maps unknown capability models: "
            f"{sorted(unknown)}"
        )
