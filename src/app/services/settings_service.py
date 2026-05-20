"""Application-facing settings service."""

from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from src.config import config

from ..errors import AppExecutionError, AppValidationError

_MASKED_VALUE = "***configured***"


class SettingsService:
    """Stable facade for configuration read/write and validation."""

    def __init__(self, config_manager=None):
        self.config = config_manager or config

    def get_settings(self, masked: bool = True) -> dict[str, Any]:
        settings = self.config.to_dict()
        return self._mask_sensitive(settings) if masked else settings

    def get_effective_settings(self, masked: bool = True) -> dict[str, Any]:
        return self.get_settings(masked=masked)

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        candidate = self.config.build_effective_config(config_override=updates)
        valid, errors = self.config.validate(candidate)
        if not valid:
            raise AppValidationError("; ".join(errors))

        try:
            self.config.persist_updates(deepcopy(updates))
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return self.get_settings(masked=True)

    def validate_settings(self, updates: dict[str, Any] | None = None) -> tuple[bool, list[str], dict[str, Any]]:
        candidate = (
            self.config.build_effective_config(config_override=deepcopy(updates))
            if updates
            else self.config.to_dict()
        )
        valid, errors = self.config.validate(candidate)
        return valid, errors, self._mask_sensitive(candidate)

    def _mask_sensitive(self, value: Any) -> Any:
        if isinstance(value, dict):
            masked: dict[str, Any] = {}
            for key, item in value.items():
                if key.endswith("_api_key"):
                    masked[key] = _MASKED_VALUE if item else ""
                else:
                    masked[key] = self._mask_sensitive(item)
            return masked
        if isinstance(value, list):
            return [self._mask_sensitive(item) for item in value]
        return value


_service: SettingsService | None = None
_lock = threading.Lock()


def get_settings_service() -> SettingsService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SettingsService()
    return _service
