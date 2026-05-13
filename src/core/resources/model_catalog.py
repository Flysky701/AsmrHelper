from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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
            raise ModelCatalogError(f"未知模型: {model_id}") from exc


def _validate_entry(raw: Dict[str, Any]) -> ModelEntry:
    required = ["id", "kind", "category", "display_name", "description"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ModelCatalogError(f"模型定义缺少字段: {', '.join(missing)}")

    kind = raw["kind"]
    category = raw["category"]
    if kind not in VALID_KINDS:
        raise ModelCatalogError(f"非法模型 kind: {kind}")
    if category not in VALID_CATEGORIES:
        raise ModelCatalogError(f"非法模型 category: {category}")

    if kind == "local" and not raw.get("install_path"):
        raise ModelCatalogError(f"本地模型缺少 install_path: {raw['id']}")

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
        required_files=list(raw.get("required_files", [])),
        required_dirs=list(raw.get("required_dirs", [])),
        supports_install=bool(raw.get("supports_install", False)),
        supports_remove=bool(raw.get("supports_remove", False)),
        install_strategy=raw.get("install_strategy"),
        upstream_name=raw.get("upstream_name"),
        api_key_config=raw.get("api_key_config"),
    )


def load_catalog_file(path: Path) -> ModelCatalog:
    if not Path(path).exists():
        raise ModelCatalogError(f"模型注册表不存在: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    models = data.get("models")
    if not isinstance(models, list):
        raise ModelCatalogError("models.yaml 缺少 models 列表")

    entries: Dict[str, ModelEntry] = {}
    for raw in models:
        entry = _validate_entry(raw)
        if entry.id in entries:
            raise ModelCatalogError(f"重复模型 ID: {entry.id}")
        entries[entry.id] = entry

    catalog = object.__new__(ModelCatalog)
    catalog._entries = entries
    catalog.path = Path(path)
    return catalog
