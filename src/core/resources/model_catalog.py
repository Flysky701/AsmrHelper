from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.config import PROJECT_ROOT


DEFAULT_CATALOG_PATH = PROJECT_ROOT / "config" / "models.yaml"
VALID_KINDS = {"local", "cloud"}
VALID_CATEGORIES = {"asr", "tts", "separator", "llm"}


class ModelCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ModelEntry:
    id: str
    kind: str
    category: str
    display_name: str
    description: str
    provider: Optional[str] = None
    engine: Optional[str] = None
    install_root: Optional[str] = None
    install_path: Optional[str] = None
    required_files: List[str] = field(default_factory=list)
    required_dirs: List[str] = field(default_factory=list)
    supports_install: bool = False
    supports_remove: bool = False
    install_strategy: Optional[str] = None
    upstream_name: Optional[str] = None
    api_key_config: Optional[str] = None
    family_id: Optional[str] = None
    variant_group: Optional[str] = None
    variant_tier: Optional[str] = None
    is_primary_variant: bool = False
    dependency_group: Optional[str] = None
    required_python_extras: List[str] = field(default_factory=list)
    required_runtime_packages: List[str] = field(default_factory=list)
    recommended_runtime_packages: List[str] = field(default_factory=list)
    optional_runtime_packages: List[str] = field(default_factory=list)
    required_assets: List[str] = field(default_factory=list)
    recommended_assets: List[str] = field(default_factory=list)
    optional_assets: List[str] = field(default_factory=list)
    runtime_profile: Optional[str] = None
    supported_os: List[str] = field(default_factory=list)
    supported_python: Dict[str, str] = field(default_factory=dict)
    requires_gpu: bool = False
    min_cuda: Optional[str] = None
    preferred_runtime: Optional[str] = None
    required_system_tools: List[str] = field(default_factory=list)
    required_binary_assets: List[str] = field(default_factory=list)
    required_vcs_features: List[str] = field(default_factory=list)
    install_modes: List[str] = field(default_factory=list)
    default_install_mode: Optional[str] = None
    auto_install_dependencies: bool = False
    install_recommended_by_default: bool = False
    allow_remote_code: bool = False
    download_sources: List[Dict[str, Any]] = field(default_factory=list)
    post_install_checks: List[Dict[str, Any]] = field(default_factory=list)
    sample_inference_policy: Dict[str, Any] = field(default_factory=dict)
    healthcheck_timeout_seconds: Optional[int] = None

    def resolved_install_root(self) -> Path:
        override_root = None
        if self.kind == "local":
            override = __import__("os").environ.get("ASMR_HELPER_MODEL_ROOT")
            if override:
                override_root = Path(override)

        if override_root is not None:
            return override_root

        if not self.install_root:
            return PROJECT_ROOT

        root = Path(self.install_root)
        if root.is_absolute():
            return root
        return PROJECT_ROOT / root

    def resolved_install_dir(self) -> Path:
        root = self.resolved_install_root()
        if not self.install_path:
            return root
        return root / Path(self.install_path)


class ModelCatalog:
    def __init__(self, path: Path | None = None):
        loaded = load_catalog_file(path or DEFAULT_CATALOG_PATH)
        self._entries = loaded._entries
        self.path = loaded.path

    def list(self, kind: str | None = None, category: str | None = None) -> List[ModelEntry]:
        entries = list(self._entries.values())
        if kind:
            entries = [entry for entry in entries if entry.kind == kind]
        if category:
            entries = [entry for entry in entries if entry.category == category]
        return entries

    def get(self, model_id: str) -> ModelEntry:
        try:
            return self._entries[model_id]
        except KeyError as exc:
            raise ModelCatalogError(f"unknown model: {model_id}") from exc


def _validate_entry(raw: Dict[str, Any]) -> ModelEntry:
    required = ["id", "kind", "category", "display_name", "description"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ModelCatalogError(f"model definition missing fields: {', '.join(missing)}")

    kind = raw["kind"]
    category = raw["category"]
    if kind not in VALID_KINDS:
        raise ModelCatalogError(f"invalid model kind: {kind}")
    if category not in VALID_CATEGORIES:
        raise ModelCatalogError(f"invalid model category: {category}")

    if kind == "local" and not raw.get("install_path"):
        raise ModelCatalogError(f"local model missing install_path: {raw['id']}")

    return ModelEntry(
        id=raw["id"],
        kind=kind,
        category=category,
        display_name=raw["display_name"],
        description=raw["description"],
        provider=raw.get("provider"),
        engine=raw.get("engine"),
        install_root=raw.get("install_root"),
        install_path=raw.get("install_path"),
        required_files=_list_of_strings(raw.get("required_files")),
        required_dirs=_list_of_strings(raw.get("required_dirs")),
        supports_install=bool(raw.get("supports_install", False)),
        supports_remove=bool(raw.get("supports_remove", False)),
        install_strategy=raw.get("install_strategy"),
        upstream_name=raw.get("upstream_name"),
        api_key_config=raw.get("api_key_config"),
        family_id=raw.get("family_id"),
        variant_group=raw.get("variant_group"),
        variant_tier=raw.get("variant_tier"),
        is_primary_variant=bool(raw.get("is_primary_variant", False)),
        dependency_group=raw.get("dependency_group"),
        required_python_extras=_list_of_strings(raw.get("required_python_extras")),
        required_runtime_packages=_list_of_strings(raw.get("required_runtime_packages")),
        recommended_runtime_packages=_list_of_strings(raw.get("recommended_runtime_packages")),
        optional_runtime_packages=_list_of_strings(raw.get("optional_runtime_packages")),
        required_assets=_list_of_strings(raw.get("required_assets")),
        recommended_assets=_list_of_strings(raw.get("recommended_assets")),
        optional_assets=_list_of_strings(raw.get("optional_assets")),
        runtime_profile=raw.get("runtime_profile"),
        supported_os=_list_of_strings(raw.get("supported_os")),
        supported_python=_string_dict(raw.get("supported_python")),
        requires_gpu=bool(raw.get("requires_gpu", False)),
        min_cuda=raw.get("min_cuda"),
        preferred_runtime=raw.get("preferred_runtime"),
        required_system_tools=_list_of_strings(raw.get("required_system_tools")),
        required_binary_assets=_list_of_strings(raw.get("required_binary_assets")),
        required_vcs_features=_list_of_strings(raw.get("required_vcs_features")),
        install_modes=_list_of_strings(raw.get("install_modes")),
        default_install_mode=raw.get("default_install_mode"),
        auto_install_dependencies=bool(raw.get("auto_install_dependencies", False)),
        install_recommended_by_default=bool(raw.get("install_recommended_by_default", False)),
        allow_remote_code=bool(raw.get("allow_remote_code", False)),
        download_sources=_list_of_dicts(raw.get("download_sources")),
        post_install_checks=_list_of_dicts(raw.get("post_install_checks")),
        sample_inference_policy=_string_keyed_dict(raw.get("sample_inference_policy")),
        healthcheck_timeout_seconds=_optional_int(raw.get("healthcheck_timeout_seconds")),
    )


def _list_of_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ModelCatalogError("metadata field must be a list of strings")
    return [str(item) for item in value if item not in (None, "")]


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ModelCatalogError("metadata field must be a list of objects")
    return [dict(item) for item in value]


def _string_dict(value: Any) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelCatalogError("supported_python must be an object")
    result: Dict[str, str] = {}
    for key, item in value.items():
        if item in (None, ""):
            continue
        result[str(key)] = str(item)
    return result


def _string_keyed_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelCatalogError("metadata field must be an object")
    return {str(key): item for key, item in value.items()}


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ModelCatalogError("healthcheck_timeout_seconds must be an integer") from exc


def load_catalog_file(path: Path) -> ModelCatalog:
    if not Path(path).exists():
        raise ModelCatalogError(f"model catalog does not exist: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    models = data.get("models")
    if not isinstance(models, list):
        raise ModelCatalogError("models.yaml is missing the models list")

    entries: Dict[str, ModelEntry] = {}
    for raw in models:
        entry = _validate_entry(raw)
        if entry.id in entries:
            raise ModelCatalogError(f"duplicate model id: {entry.id}")
        entries[entry.id] = entry

    catalog = object.__new__(ModelCatalog)
    catalog._entries = entries
    catalog.path = Path(path)
    return catalog
