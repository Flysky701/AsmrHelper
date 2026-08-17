"""Short-lived provider verification facts used by cloud-model readiness.

The registry deliberately stores only a one-way configuration fingerprint.  A
status lookup therefore remains local and cannot expose credentials or trigger
a network request. Records are process-local, so an application restart also
invalidates every verification fact.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable


DEFAULT_PROVIDER_VERIFICATION_TTL_SECONDS = 15 * 60
_MAX_RECORDS_PER_PROVIDER = 8


@dataclass(frozen=True)
class ProviderVerificationRecord:
    provider: str
    configuration_fingerprint: str
    success: bool
    checked_at: float
    expires_at: float
    message: str = ""
    error_code: str | None = None


class ProviderVerificationRegistry:
    """Hold bounded, expiring verification results for provider configurations."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_PROVIDER_VERIFICATION_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("provider verification TTL must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock or time.monotonic
        self._records: dict[tuple[str, str], ProviderVerificationRecord] = {}
        self._lock = threading.RLock()

    def record_success(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        *,
        message: str = "",
    ) -> ProviderVerificationRecord:
        return self._record(
            provider,
            api_key,
            base_url,
            success=True,
            message=message,
            error_code=None,
        )

    def record_failure(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        *,
        message: str,
        error_code: str,
    ) -> ProviderVerificationRecord:
        return self._record(
            provider,
            api_key,
            base_url,
            success=False,
            message=message,
            error_code=error_code,
        )

    def get_fresh(
        self,
        provider: str,
        api_key: str,
        base_url: str,
    ) -> ProviderVerificationRecord | None:
        """Return a matching, unexpired fact without performing provider I/O."""
        key = self._record_key(provider, api_key, base_url)
        now = self._clock()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if now >= record.expires_at:
                self._records.pop(key, None)
                return None
            return record

    def invalidate_provider(self, provider: str) -> None:
        normalized = self._normalize_provider(provider)
        with self._lock:
            self._records = {
                key: record
                for key, record in self._records.items()
                if key[0] != normalized
            }

    def _record(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        *,
        success: bool,
        message: str,
        error_code: str | None,
    ) -> ProviderVerificationRecord:
        key = self._record_key(provider, api_key, base_url)
        now = self._clock()
        record = ProviderVerificationRecord(
            provider=key[0],
            configuration_fingerprint=key[1],
            success=success,
            checked_at=now,
            expires_at=now + self._ttl_seconds,
            message=message,
            error_code=error_code,
        )
        with self._lock:
            self._records[key] = record
            self._prune_provider(key[0], now=now)
        return record

    def _prune_provider(self, provider: str, *, now: float) -> None:
        for key, record in list(self._records.items()):
            if key[0] == provider and now >= record.expires_at:
                self._records.pop(key, None)

        provider_records = sorted(
            (
                (key, record)
                for key, record in self._records.items()
                if key[0] == provider
            ),
            key=lambda item: item[1].checked_at,
        )
        for key, _record in provider_records[:-_MAX_RECORDS_PER_PROVIDER]:
            self._records.pop(key, None)

    @classmethod
    def _record_key(
        cls,
        provider: str,
        api_key: str,
        base_url: str,
    ) -> tuple[str, str]:
        normalized_provider = cls._normalize_provider(provider)
        normalized_api_key = str(api_key or "").strip()
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        payload = "\0".join(
            (normalized_provider, normalized_api_key, normalized_base_url)
        ).encode("utf-8")
        return normalized_provider, hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        return str(provider or "").strip().lower()


_registry: ProviderVerificationRegistry | None = None
_registry_lock = threading.Lock()


def get_provider_verification_registry() -> ProviderVerificationRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ProviderVerificationRegistry()
    return _registry
