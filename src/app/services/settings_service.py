"""Application-facing settings service."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.config import config
from src.provider_profiles import public_profiles, update_profiles
from src.core.engines.llm.registry import LLM_DEFAULT_MODELS
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


class ProviderModelsError(AppExecutionError):
    """A safe, stable error from model discovery (never includes upstream text)."""

    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class SettingsService:
    """Stable facade for configuration read/write and validation."""

    def __init__(
        self,
        config_manager=None,
        provider_probe=None,
        verification_registry: ProviderVerificationRegistry | None = None,
        model_probe=None,
    ):
        self.config = config_manager or config
        self._provider_probe = provider_probe or self._probe_openai_compatible
        self._model_probe = model_probe or self._list_openai_compatible_models
        self._verification_registry = verification_registry or get_provider_verification_registry()

    def get_settings(self, masked: bool = True) -> dict[str, Any]:
        settings = self.config.to_dict()
        return self._to_public_settings(settings) if masked else settings


    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        with getattr(self.config, "_state_lock", nullcontext()):
            return self._update_settings_locked(updates)

    def _update_settings_locked(self, updates: dict[str, Any]) -> dict[str, Any]:
        internal_updates = self._to_internal_updates(updates)
        candidate = self.config.build_effective_config(config_override=internal_updates)
        valid, errors = self._validate_candidate(candidate, updates)
        if not valid:
            raise AppValidationError("; ".join(errors))

        try:
            self.config.persist_updates(deepcopy(internal_updates))
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return self.get_settings(masked=True)

    def validate_settings(
        self, updates: dict[str, Any] | None = None
    ) -> tuple[bool, list[str], dict[str, Any]]:
        internal_updates = self._to_internal_updates(updates or {})
        candidate = (
            self.config.build_effective_config(config_override=deepcopy(internal_updates))
            if updates
            else self.config.to_dict()
        )
        valid, errors = self._validate_candidate(candidate, updates)
        return valid, errors, self._to_public_settings(candidate)

    def _validate_candidate(self, candidate, requested_updates):
        # Preflight and persistence must use the same scope. Profile migration can
        # add connection_profiles internally even when only a local path changed.
        local_only = bool(requested_updates) and set(requested_updates) <= {"paths", "processing"}
        from src.workspace_paths import path_setting_errors
        path_errors = path_setting_errors((requested_updates or {}).get("paths", {}))
        if local_only:
            valid, errors = self.config.validate(candidate, require_api_key=False)
            errors = list(errors) + path_errors
            return valid and not errors, errors
        valid, errors = self.config.validate(candidate)
        errors = list(errors) + self._profile_validation_errors(candidate) + path_errors
        return valid and not errors, errors

    @staticmethod
    def _profile_validation_errors(candidate):
        profiles = candidate.get("connection_profiles", {})
        selected = next((p for p in profiles.get("llm", []) if p["id"] == profiles.get("active_llm")), None)
        if selected and not selected["id"].startswith("legacy-") and not str(selected.get("model") or "").strip():
            return ["请探测并选择模型，或手动填写模型 ID"]
        return []

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

    def discover_models(
        self, provider: str, settings: dict[str, Any] | None = None,
    ) -> list[str]:
        """Read model IDs from a draft connection without saving any settings."""
        from urllib.parse import urlsplit

        if provider not in _SUPPORTED_PROVIDERS:
            raise ProviderModelsError("PROVIDER_NOT_FOUND", "不支持的服务提供商", 400)
        updates = self._to_internal_updates(settings or {})
        candidate = self.config.build_effective_config(config_override=deepcopy(updates))
        if settings and ("connection_profile" in settings or "active_connections" in settings):
            if candidate.get("api", {}).get("provider") != provider:
                raise ProviderModelsError("PROVIDER_MISMATCH", "所选配置与服务提供商不一致", 400)
        api = candidate.get("api", {})
        api_key = api.get(f"{provider}_api_key")
        base_url = api.get(f"{provider}_base_url")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderModelsError("PROVIDER_CREDENTIAL_MISSING", "请先填写 API Key", 400)
        try:
            url = urlsplit(base_url) if isinstance(base_url, str) else None
            valid_url = bool(
                url and url.scheme in ("http", "https") and url.hostname
                and not url.username and not url.password and not url.query and not url.fragment
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ProviderModelsError("PROVIDER_URL_INVALID", "请填写有效的 HTTP(S) 基础地址", 400)
        try:
            ids = self._model_probe(provider, api_key.strip(), base_url.strip())
        except Exception as exc:
            from openai import APITimeoutError

            status = getattr(exc, "status_code", None)
            if isinstance(exc, (APITimeoutError, TimeoutError)):
                raise ProviderModelsError("PROVIDER_TIMEOUT", "获取模型超时，请稍后重试", 504) from exc
            if status in (401, 403):
                raise ProviderModelsError("PROVIDER_AUTH_FAILED", "鉴权失败，请检查 API Key 与访问权限") from exc
            if status in (404, 405, 501):
                raise ProviderModelsError("PROVIDER_MODELS_UNSUPPORTED", "该地址不支持模型列表，请检查服务文档与基础地址") from exc
            if status == 429:
                raise ProviderModelsError("PROVIDER_RATE_LIMITED", "服务请求受限，请稍后重试") from exc
            raise ProviderModelsError("PROVIDER_CONNECTION_FAILED", "无法获取模型，请检查连接信息及服务状态") from exc
        if not isinstance(ids, list) or len(ids) > 10000 or any(
            not isinstance(model, str) or not model or len(model) > 512
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in model)
            for model in ids
        ):
            raise ProviderModelsError("PROVIDER_MODELS_INVALID", "服务返回的模型列表格式无效")
        return sorted(set(ids))

    @staticmethod
    def _list_openai_compatible_models(
        provider: str, api_key: str, base_url: str,
    ) -> list[Any] | None:
        from openai import OpenAI

        with OpenAI(api_key=api_key, base_url=base_url, timeout=10.0, max_retries=0) as client:
            page = client.models.list()
            # Reading data avoids the SDK's automatic pagination iterator.
            if not isinstance(page.data, list):
                return None
            return [getattr(model, "id", None) for model in page.data]

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
            "paths": deepcopy(settings.get("paths", {})),
            "processing": deepcopy(settings.get("processing", {})),
        }
        for provider in _SUPPORTED_PROVIDERS:
            public["providers"][provider] = {
                "base_url": api.get(f"{provider}_base_url", ""),
                "model": api.get(f"{provider}_model") or LLM_DEFAULT_MODELS[provider],
                "credential_configured": bool(api.get(f"{provider}_api_key")),
            }
        public["connection_profiles"] = public_profiles(settings)
        return public

    def _to_internal_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Map Provider v1 writes to the existing Config shape.

        The legacy ``api`` shape remains accepted during the migration, but masked
        placeholders are always ignored so they can never replace a real key.
        """
        if not isinstance(updates, dict):
            raise AppValidationError("settings 必须是对象")

        internal: dict[str, Any] = {}
        if "external_tts" in updates or "tts" in updates:
            raise AppValidationError("旧 TTS 配置已只读，请在外部服务管理中配置 Speech 语音连接")
        for section in ("paths", "processing"):
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
                if "model" in provider_settings:
                    model = provider_settings["model"]
                    if not isinstance(model, str) or not model.strip():
                        raise AppValidationError("模型 ID 不能为空")
                    api_updates[f"{provider}_model"] = model.strip()
                credential = provider_settings.get("credential")
                if credential not in ("", _MASKED_VALUE, None):
                    api_updates[f"{provider}_api_key"] = credential
            if not api_updates:
                internal.pop("api", None)
        # Migrate only when profiles are first edited, preserving raw disk secrets
        # rather than persisting environment overrides.
        if hasattr(self.config, "get_file_config"):
            base = self.config.build_effective_config(include_env=False)
        else:
            base = self.config.build_effective_config()
        if "connection_profiles" in base or "connection_profile" in updates or "active_connections" in updates:
            try:
                internal["connection_profiles"] = update_profiles(base, updates, internal)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
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
