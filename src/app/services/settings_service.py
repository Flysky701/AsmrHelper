"""Application-facing settings service."""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.config import config
from src.core.resources.provider_verification import (
    ProviderVerificationRegistry,
    get_provider_verification_registry,
)

from ..errors import AppExecutionError, AppValidationError

_MASKED_VALUE = "***configured***"
_SUPPORTED_PROVIDERS = ("deepseek", "openai")


@dataclass(frozen=True)
class ProviderTestResult:
    provider: str
    success: bool
    error_code: str | None = None
    message: str = ""


class SettingsService:
    """Stable facade for configuration read/write and validation."""

    def __init__(
        self,
        config_manager=None,
        provider_probe=None,
        verification_registry: ProviderVerificationRegistry | None = None,
    ):
        self.config = config_manager or config
        self._provider_probe = provider_probe or self._probe_openai_compatible
        self._verification_registry = (
            verification_registry or get_provider_verification_registry()
        )

    def get_settings(self, masked: bool = True) -> dict[str, Any]:
        settings = self.config.to_dict()
        return self._to_public_settings(settings) if masked else settings


    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        internal_updates = self._to_internal_updates(updates)
        candidate = self.config.build_effective_config(config_override=internal_updates)
        valid, errors = self.config.validate(candidate)
        if not valid:
            raise AppValidationError("; ".join(errors))

        try:
            self.config.persist_updates(deepcopy(internal_updates))
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return self.get_settings(masked=True)

    def validate_settings(self, updates: dict[str, Any] | None = None) -> tuple[bool, list[str], dict[str, Any]]:
        internal_updates = self._to_internal_updates(updates or {})
        candidate = (
            self.config.build_effective_config(config_override=deepcopy(internal_updates))
            if updates
            else self.config.to_dict()
        )
        valid, errors = self.config.validate(candidate)
        return valid, errors, self._to_public_settings(candidate)

    def test_provider(
        self,
        provider: str,
        settings: dict[str, Any] | None = None,
    ) -> ProviderTestResult:
        if provider not in _SUPPORTED_PROVIDERS:
            return ProviderTestResult(
                provider=provider,
                success=False,
                error_code="PROVIDER_NOT_FOUND",
                message=f"不支持的 Provider：{provider}",
            )

        internal_updates = self._to_internal_updates(settings or {})
        candidate = (
            self.config.build_effective_config(config_override=deepcopy(internal_updates))
            if settings
            else self.config.to_dict()
        )
        api_settings = candidate.get("api", {}) if isinstance(candidate, dict) else {}
        api_key = str(api_settings.get(f"{provider}_api_key") or "").strip()
        base_url = str(api_settings.get(f"{provider}_base_url") or "").strip()
        if not api_key:
            return ProviderTestResult(
                provider=provider,
                success=False,
                error_code="PROVIDER_CREDENTIAL_MISSING",
                message=f"{provider} 尚未配置 API Key",
            )

        try:
            self._provider_probe(provider, api_key, base_url)
        except Exception as exc:
            result = ProviderTestResult(
                provider=provider,
                success=False,
                error_code="PROVIDER_CONNECTION_FAILED",
                message=self._safe_provider_error(exc, secrets=(api_key,)),
            )
            self._verification_registry.record_failure(
                provider,
                api_key,
                base_url,
                message=result.message,
                error_code=result.error_code,
            )
            return result
        result = ProviderTestResult(
            provider=provider,
            success=True,
            message=f"{provider} 连接与鉴权验证成功",
        )
        self._verification_registry.record_success(
            provider,
            api_key,
            base_url,
            message=result.message,
        )
        return result

    @staticmethod
    def _probe_openai_compatible(provider: str, api_key: str, base_url: str) -> None:
        """Perform a real, low-cost connectivity/authentication request."""
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=10.0)
        client.models.list()

    @staticmethod
    def _safe_provider_error(
        exc: Exception,
        *,
        secrets: tuple[str, ...] = (),
    ) -> str:
        detail = " ".join(str(exc).split())
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        if len(detail) > 300:
            detail = f"{detail[:297]}..."
        return f"Provider 连接或鉴权失败：{detail or type(exc).__name__}"

    def _to_public_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Expose a stable view without returning secret-shaped placeholder values."""
        api = settings.get("api", {}) if isinstance(settings, dict) else {}
        public = {
            "providers": {
                "default_llm": api.get("provider", "deepseek"),
            },
            "tts": deepcopy(settings.get("tts", {})),
            "paths": deepcopy(settings.get("paths", {})),
            "processing": deepcopy(settings.get("processing", {})),
        }
        for provider in _SUPPORTED_PROVIDERS:
            public["providers"][provider] = {
                "base_url": api.get(f"{provider}_base_url", ""),
                "credential_configured": bool(api.get(f"{provider}_api_key")),
            }
        return public

    def _to_internal_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Map Provider v1 writes to the existing Config shape.

        The legacy ``api`` shape remains accepted during the migration, but masked
        placeholders are always ignored so they can never replace a real key.
        """
        if not isinstance(updates, dict):
            raise AppValidationError("settings 必须是对象")

        internal: dict[str, Any] = {}
        for section in ("tts", "paths", "processing"):
            value = updates.get(section)
            if isinstance(value, dict):
                internal[section] = deepcopy(value)

        legacy_api = updates.get("api")
        if isinstance(legacy_api, dict):
            api_updates = deepcopy(legacy_api)
            for key in ("deepseek_api_key", "openai_api_key"):
                if api_updates.get(key) in ("", _MASKED_VALUE, None):
                    api_updates.pop(key, None)
            if api_updates:
                internal["api"] = api_updates

        providers = updates.get("providers")
        if isinstance(providers, dict):
            api_updates = internal.setdefault("api", {})
            if "default_llm" in providers:
                api_updates["provider"] = providers["default_llm"]
            for provider in _SUPPORTED_PROVIDERS:
                provider_settings = providers.get(provider)
                if not isinstance(provider_settings, dict):
                    continue
                if "base_url" in provider_settings:
                    api_updates[f"{provider}_base_url"] = provider_settings["base_url"]
                credential = provider_settings.get("credential")
                if credential not in ("", _MASKED_VALUE, None):
                    api_updates[f"{provider}_api_key"] = credential
            if not api_updates:
                internal.pop("api", None)
        return internal


_service: SettingsService | None = None
_lock = threading.Lock()


def get_settings_service() -> SettingsService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SettingsService()
    return _service
