"""Separator engine registry — domain-scoped provider registration and instantiation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass(frozen=True)
class SeparatorProviderEntry:
    name: str
    factory: Callable[..., Any]
    config_defaults: dict[str, str]


class SeparatorRegistry:
    """Registry for audio separator providers."""

    _instance: SeparatorRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._providers: dict[str, SeparatorProviderEntry] = {}
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> SeparatorRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._register_builtins()
        return cls._instance

    def _register_builtins(self) -> None:
        self.register(
            "demucs",
            factory=self._make_separator,
            config_defaults={"model_name": "processing.vocal_model"},
        )

    def register(
        self,
        name: str,
        *,
        factory: Callable[..., Any],
        config_defaults: dict[str, str] | None = None,
    ) -> None:
        self._providers[name] = SeparatorProviderEntry(
            name=name,
            factory=factory,
            config_defaults=config_defaults or {},
        )

    def available(self) -> list[str]:
        return list(self._providers.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._providers

    def get(self, name: str, **kwargs: Any) -> Any:
        if name not in self._providers:
            raise ValueError(f"unknown separator provider: {name!r} (available: {self.available()})")

        entry = self._providers[name]
        resolved = self._resolve_defaults(entry.config_defaults)
        resolved.update(kwargs)
        cache_key = self._make_cache_key(name, resolved)
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        instance = entry.factory(**resolved)

        with self._cache_lock:
            self._cache[cache_key] = instance
        return instance

    def unload(self, name: str) -> None:
        with self._cache_lock:
            instances = [
                self._cache.pop(cache_key)
                for cache_key in [key for key in self._cache if key.startswith(f"separator/{name}|")]
            ]
        for instance in instances:
            if hasattr(instance, "unload"):
                instance.unload()
        if instances:
            self._try_clear_cuda()

    def unload_all(self) -> None:
        with self._cache_lock:
            instances = list(self._cache.values())
            self._cache.clear()
        for instance in instances:
            if hasattr(instance, "unload"):
                instance.unload()
        self._try_clear_cuda()

    def is_loaded(self, name: str) -> bool:
        with self._cache_lock:
            return any(key.startswith(f"separator/{name}|") for key in self._cache)

    @staticmethod
    def _resolve_defaults(config_defaults: dict[str, str]) -> dict[str, Any]:
        from src.config import Config
        config = Config()
        resolved = {}
        for param_name, config_path in config_defaults.items():
            resolved[param_name] = config.get(config_path)
        return resolved

    @staticmethod
    def _make_cache_key(name: str, resolved: dict[str, Any]) -> str:
        normalized = json.dumps(resolved, sort_keys=True, ensure_ascii=True, default=str)
        return f"separator/{name}|{normalized}"

    @staticmethod
    def _make_separator(**kwargs: Any) -> Any:
        from src.core.vocal_separator import VocalSeparator
        return VocalSeparator(**kwargs)

    @staticmethod
    def _try_clear_cuda() -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def get_separator_registry() -> SeparatorRegistry:
    return SeparatorRegistry.get_instance()
