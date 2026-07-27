"""LLM engine registry — domain-scoped provider registration and instantiation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
import json
from typing import Any, Callable


LLM_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
}

LLM_SUPPORTED_MODELS: dict[str, list[str]] = {
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    ],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
}


@dataclass(frozen=True)
class LlmProviderEntry:
    name: str
    factory: Callable[..., Any]
    config_defaults: dict[str, str]


class LlmRegistry:
    """Registry for LLM providers."""

    _instance: LlmRegistry | None = None
    _lock = threading.Lock()

    # Default model names per provider (used when caller passes empty/'default')
    DEFAULT_MODELS = LLM_DEFAULT_MODELS
    SUPPORTED_MODELS = LLM_SUPPORTED_MODELS

    def __init__(self) -> None:
        self._providers: dict[str, LlmProviderEntry] = {}
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> LlmRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._register_builtins()
        return cls._instance

    def _register_builtins(self) -> None:
        self.register(
            "deepseek",
            factory=self._make_deepseek_llm,
            config_defaults={
                "api_key": "api.deepseek_api_key",
                "base_url": "api.deepseek_base_url",
            },
        )
        self.register(
            "openai",
            factory=self._make_openai_llm,
            config_defaults={
                "api_key": "api.openai_api_key",
                "base_url": "api.openai_base_url",
            },
        )

    def register(
        self,
        name: str,
        *,
        factory: Callable[..., Any],
        config_defaults: dict[str, str] | None = None,
    ) -> None:
        self._providers[name] = LlmProviderEntry(
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
            raise ValueError(f"unknown LLM provider: {name!r} (available: {self.available()})")

        # Normalize model name: empty / 'default' → provider's default model
        raw_model = kwargs.get("model", "")
        if not raw_model or str(raw_model).strip().lower() in ("", "default"):
            kwargs["model"] = self.DEFAULT_MODELS.get(name, "")
        # Drop empty base_url so Translator falls back to provider's built-in default
        if kwargs.get("base_url") in (None, ""):
            kwargs.pop("base_url", None)

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

    def list_models(self, name: str) -> list[str]:
        """List supported model names for a provider."""
        return list(self.SUPPORTED_MODELS.get(name, []))

    def default_model(self, name: str) -> str:
        """Get the default model name for a provider."""
        return self.DEFAULT_MODELS.get(name, "")

    def unload(self, name: str) -> None:
        with self._cache_lock:
            for cache_key in [key for key in self._cache if key.startswith(f"llm/{name}|")]:
                self._cache.pop(cache_key, None)

    def unload_all(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def is_loaded(self, name: str) -> bool:
        with self._cache_lock:
            return any(key.startswith(f"llm/{name}|") for key in self._cache)

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
        return f"llm/{name}|{normalized}"

    @staticmethod
    def _make_deepseek_llm(**kwargs: Any) -> Any:
        from .translator import Translator
        return Translator(provider="deepseek", **kwargs)

    @staticmethod
    def _make_openai_llm(**kwargs: Any) -> Any:
        from .translator import Translator
        return Translator(provider="openai", **kwargs)


def get_llm_registry() -> LlmRegistry:
    return LlmRegistry.get_instance()
