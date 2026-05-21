"""ASR engine registry — domain-scoped provider registration and instantiation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass(frozen=True)
class AsrProviderEntry:
    name: str
    factory: Callable[..., Any]
    config_defaults: dict[str, str]


class AsrRegistry:
    """Registry for ASR providers."""

    _instance: AsrRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._providers: dict[str, AsrProviderEntry] = {}
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> AsrRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._register_builtins()
        return cls._instance

    def _register_builtins(self) -> None:
        self.register(
            "faster_whisper",
            factory=self._make_asr,
            config_defaults={"model_size": "processing.asr_model"},
        )
        self.register(
            "fun_asr",
            factory=self._make_fun_asr,
        )
        self.register(
            "qwen3_asr",
            factory=self._make_qwen3_asr,
        )

    def register(
        self,
        name: str,
        *,
        factory: Callable[..., Any],
        config_defaults: dict[str, str] | None = None,
    ) -> None:
        self._providers[name] = AsrProviderEntry(
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
            raise ValueError(f"unknown ASR provider: {name!r} (available: {self.available()})")

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
                for cache_key in [key for key in self._cache if key.startswith(f"asr/{name}|")]
            ]
        for instance in instances:
            if hasattr(instance, "unload"):
                instance.unload()

    def unload_all(self) -> None:
        with self._cache_lock:
            instances = list(self._cache.values())
            self._cache.clear()
        for instance in instances:
            if hasattr(instance, "unload"):
                instance.unload()

    def is_loaded(self, name: str) -> bool:
        with self._cache_lock:
            return any(key.startswith(f"asr/{name}|") for key in self._cache)

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
        return f"asr/{name}|{normalized}"

    @staticmethod
    def _make_asr(**kwargs: Any) -> Any:
        from src.core.asr import ASRRecognizer
        return ASRRecognizer(**kwargs)

    @staticmethod
    def _make_fun_asr(**kwargs: Any) -> Any:
        from .fun_asr import FunAsrRecognizer

        return FunAsrRecognizer(**kwargs)

    @staticmethod
    def _make_qwen3_asr(**kwargs: Any) -> Any:
        from .qwen3_asr import Qwen3AsrRecognizer

        return Qwen3AsrRecognizer(**kwargs)


def get_asr_registry() -> AsrRegistry:
    return AsrRegistry.get_instance()
