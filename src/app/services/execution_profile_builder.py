"""Execution profile builder service."""

from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from ..errors import AppValidationError
from .capability_descriptor_service import CapabilityDescriptorService, get_capability_descriptor_service
from .settings_service import SettingsService, get_settings_service


class ExecutionProfileBuilder:
    """Builds normalized execution profiles from defaults and explicit inputs."""

    def __init__(
        self,
        settings_service: SettingsService | None = None,
        descriptor_service: CapabilityDescriptorService | None = None,
    ):
        self.settings_service = settings_service or get_settings_service()
        self.descriptor_service = descriptor_service or get_capability_descriptor_service()

    def build(
        self,
        *,
        category: str,
        provider: str | None = None,
        model: str | None = None,
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = self.settings_service.get_settings(masked=False)

        # Resolve model first so provider can be inferred from model_id.
        resolved_model = model or self._default_model(category, settings=settings)
        resolved_provider = provider or self._default_provider(category, settings, resolved_model)
        descriptor = self.descriptor_service.get_descriptor(category, resolved_provider)

        # Re-resolve model against descriptor if it was not explicitly provided.
        if not model:
            resolved_model = self._default_model(category, settings, descriptor)

        # Normalize 'default' alias to descriptor's actual default_model
        resolved_model = self._normalize_model(resolved_model, descriptor)

        self._validate_supported_model(descriptor, resolved_model)

        resolved_common = self._fill_defaults(
            descriptor["common_option_schema"],
            common_options or {},
        )
        resolved_provider_options = self._fill_defaults(
            descriptor["provider_option_schema"],
            provider_options or {},
        )
        self.descriptor_service.validate_options(
            category=category,
            provider=resolved_provider,
            common_options=resolved_common,
            provider_options=resolved_provider_options,
        )

        return {
            "category": category,
            "provider": resolved_provider,
            "model": resolved_model,
            "common_options": resolved_common,
            "provider_options": resolved_provider_options,
        }

    def _default_provider(
        self, category: str, settings: dict[str, Any], model: str | None = None,
    ) -> str:
        if category == "asr" and model:
            if model.startswith("faster-whisper-"):
                return "faster_whisper"
            if model.startswith("fun-asr-"):
                return "fun_asr"
            if model.startswith("qwen3-asr-"):
                return "qwen3_asr"
        if category == "tts":
            return settings.get("tts", {}).get("engine", "edge")
        if category == "llm":
            return settings.get("api", {}).get("provider", "deepseek")
        if category == "asr":
            return "faster_whisper"
        if category == "separator":
            return "demucs"
        raise AppValidationError(f"unsupported execution profile category: {category}")

    def _default_model(
        self,
        category: str,
        settings: dict[str, Any],
        descriptor: dict[str, Any] | None = None,
    ) -> str:
        fallback = descriptor["default_model"] if descriptor else None
        if category == "asr":
            candidate = str(settings.get("processing", {}).get("asr_model", fallback or "faster-whisper-base"))
            if descriptor:
                supported = descriptor.get("supported_models", [])
                if supported and candidate not in supported:
                    return str(descriptor["default_model"])
            return candidate
        if category == "separator":
            return str(settings.get("processing", {}).get("vocal_model", fallback or "htdemucs"))
        return str(fallback or "default")

    def _fill_defaults(
        self,
        schema_entries: list[dict[str, Any]],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        remaining = deepcopy(overrides)
        for entry in schema_entries:
            name = entry["name"]
            if name in remaining:
                resolved[name] = remaining.pop(name)
            elif entry.get("default") is not None:
                resolved[name] = entry["default"]
            elif entry.get("required"):
                raise AppValidationError(f"missing required option: {name}")
        resolved.update(remaining)
        return resolved

    def _validate_supported_model(self, descriptor: dict[str, Any], model: str):
        supported = descriptor.get("supported_models", [])
        if supported and model not in supported:
            raise AppValidationError(
                f"unsupported model '{model}' for {descriptor['category']}/{descriptor['provider']}"
            )

    @staticmethod
    def _normalize_model(model: str | None, descriptor: dict[str, Any]) -> str:
        """Normalize 'default' / empty to the descriptor's default_model."""
        if not model or str(model).strip().lower() in ("", "default"):
            return str(descriptor.get("default_model", "default"))
        return str(model)


_service: ExecutionProfileBuilder | None = None
_lock = threading.Lock()


def get_execution_profile_builder() -> ExecutionProfileBuilder:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ExecutionProfileBuilder()
    return _service
