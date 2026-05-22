"""TTS engine registry — domain-scoped provider registration and instantiation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass(frozen=True)
class TtsProviderEntry:
    name: str
    factory: Callable[..., Any]
    config_defaults: dict[str, str]


class TtsRegistry:
    """Registry for TTS providers.

    Each provider has a factory function and a mapping of config keys
    to Config paths for default resolution.
    """

    _instance: TtsRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._providers: dict[str, TtsProviderEntry] = {}
        self._cache: dict[str, Any] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TtsRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._register_builtins()
        return cls._instance

    def _register_builtins(self) -> None:
        self.register(
            "edge",
            factory=self._make_edge_tts,
            config_defaults={"voice": "tts.voice"},
        )
        self.register(
            "qwen3",
            factory=self._make_qwen3_tts,
            config_defaults={"voice": "tts.voice", "speed": "tts.speed"},
        )
        self.register(
            "kokoro",
            factory=self._make_kokoro_tts,
            config_defaults={},
        )

    def register(
        self,
        name: str,
        *,
        factory: Callable[..., Any],
        config_defaults: dict[str, str] | None = None,
    ) -> None:
        self._providers[name] = TtsProviderEntry(
            name=name,
            factory=factory,
            config_defaults=config_defaults or {},
        )

    def available(self) -> list[str]:
        return list(self._providers.keys())

    def list_voices(self, name: str) -> list[dict]:
        """Return available voices for a registered TTS provider."""
        if name not in self._providers:
            raise ValueError(f"unknown TTS provider: {name!r} (available: {self.available()})")
        factory = self._providers[name].factory
        # The factory returns a TTSEngine wrapper; get the underlying engine class
        import src.core.tts as tts_module
        engine_map = {
            "edge": tts_module.EdgeTTSEngine,
            "qwen3": tts_module.Qwen3TTSEngine,
        }
        engine_cls = engine_map.get(name)
        if engine_cls and hasattr(engine_cls, "list_voices"):
            return engine_cls.list_voices()
        # kokoro: return common voices from the engine class
        if name == "kokoro":
            from .kokoro import KokoroTtsEngine
            return KokoroTtsEngine.list_voices()
        return []

    def is_registered(self, name: str) -> bool:
        return name in self._providers

    def get(self, name: str, **kwargs: Any) -> Any:
        if name not in self._providers:
            raise ValueError(f"unknown TTS provider: {name!r} (available: {self.available()})")

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
                for cache_key in [key for key in self._cache if key.startswith(f"tts/{name}|")]
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
            return any(key.startswith(f"tts/{name}|") for key in self._cache)

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
        return f"tts/{name}|{normalized}"

    @staticmethod
    def _make_edge_tts(**kwargs: Any) -> Any:
        from src.core.tts import TTSEngine
        return TTSEngine(engine="edge", **kwargs)

    @staticmethod
    def _make_qwen3_tts(**kwargs: Any) -> Any:
        from src.core.tts import TTSEngine
        return TTSEngine(engine="qwen3", **kwargs)

    @staticmethod
    def _make_kokoro_tts(**kwargs: Any) -> Any:
        from .kokoro import KokoroTtsEngine

        return KokoroTtsEngine(**kwargs)


def get_tts_registry() -> TtsRegistry:
    return TtsRegistry.get_instance()
