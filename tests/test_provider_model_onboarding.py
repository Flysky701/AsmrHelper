from __future__ import annotations

from typing import Any

from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.core.resources.model_catalog import ModelCatalog, ModelEntry


def _backend(entry: ModelEntry) -> str:
    return entry.provider or entry.engine or ""


def _descriptors() -> dict[tuple[str, str], dict[str, Any]]:
    items = CapabilityDescriptorService().list_descriptors()
    return {(item["category"], item["provider"]): item for item in items}


def _matches_type(type_name: str, value: Any) -> bool:
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


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
            and _backend(entry) == descriptor["provider"]
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


def test_capability_descriptors_have_valid_model_and_option_contracts() -> None:
    descriptors = CapabilityDescriptorService().list_descriptors()
    keys = [(item["category"], item["provider"]) for item in descriptors]
    assert len(keys) == len(set(keys)), "capability category/provider pairs must be unique"

    for descriptor in descriptors:
        label = f"{descriptor['category']}/{descriptor['provider']}"
        supported_models = descriptor["supported_models"]
        assert supported_models, f"{label} must advertise at least one model"
        assert len(supported_models) == len(set(supported_models)), (
            f"{label} contains duplicate supported model ids"
        )
        assert descriptor["default_model"] in supported_models, (
            f"{label} default_model must be included in supported_models"
        )

        options = [
            *descriptor["common_option_schema"],
            *descriptor["provider_option_schema"],
        ]
        names = [option["name"] for option in options]
        assert len(names) == len(set(names)), f"{label} contains duplicate option names"

        for option in options:
            option_label = f"{label}.{option['name']}"
            assert option["type"] in {
                "boolean",
                "integer",
                "number",
                "string",
                "array",
                "object",
            }, f"{option_label} uses an unsupported option type"

            default = option["default"]
            if default is not None:
                assert _matches_type(option["type"], default), (
                    f"{option_label} default does not match declared type"
                )
                if option["enum"]:
                    assert default in option["enum"], (
                        f"{option_label} default is not included in enum"
                    )
                if option["min"] is not None:
                    assert default >= option["min"], (
                        f"{option_label} default is below min"
                    )
                if option["max"] is not None:
                    assert default <= option["max"], (
                        f"{option_label} default is above max"
                    )

            if option["min"] is not None and option["max"] is not None:
                assert option["min"] <= option["max"], (
                    f"{option_label} min must not exceed max"
                )
