"""Provider verification facts used by cloud-model readiness.

The registry deliberately stores only a one-way configuration fingerprint.  A
status lookup therefore remains local and cannot expose credentials or trigger
a network request. The application registry persists successful, expiring facts
so reopening the desktop app does not force another provider probe.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
from dataclasses import dataclass
from typing import Callable


DEFAULT_PROVIDER_VERIFICATION_TTL_SECONDS = 24 * 60 * 60
_MAX_RECORDS_PER_PROVIDER = 8
_STORAGE_VERSION = 1
_MAX_CLOCK_SKEW_SECONDS = 5 * 60

logger = logging.getLogger(__name__)


class ProviderVerificationPersistenceError(RuntimeError):
    """Raised when a stale success cannot be durably revoked."""


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
        storage_path: Path | str | None = None,
    ) -> None:
        normalized_ttl = float(ttl_seconds)
        if not math.isfinite(normalized_ttl) or normalized_ttl <= 0:
            raise ValueError("provider verification TTL must be positive")
        self._ttl_seconds = normalized_ttl
        self._clock = clock or time.time
        self._storage_path = (
            Path(storage_path).expanduser().resolve() if storage_path else None
        )
        self._records: dict[tuple[str, str], ProviderVerificationRecord] = {}
        self._lock = threading.RLock()
        if self._storage_path is not None:
            with self._lock:
                self._load_persisted_records(now=self._now())

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
        now = self._now()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if now >= record.expires_at:
                self._records.pop(key, None)
                self._persist_or_discard()
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
            self._persist_or_discard()

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
        now = self._now()
        expires_at = now + self._ttl_seconds
        if not math.isfinite(expires_at):
            raise ValueError("provider verification expiry must be finite")
        record = ProviderVerificationRecord(
            provider=key[0],
            configuration_fingerprint=key[1],
            success=success,
            checked_at=now,
            expires_at=expires_at,
            message=message,
            error_code=error_code,
        )
        with self._lock:
            self._records[key] = record
            self._prune_provider(key[0], now=now)
            if success:
                self._persist_successes()
            else:
                self._persist_or_discard()
        return record

    def _load_persisted_records(self, *, now: float) -> None:
        assert self._storage_path is not None
        try:
            if self._revocation_path().exists():
                return
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            if payload.get("version") != _STORAGE_VERSION:
                return
            raw_records = payload.get("records", [])
            if not isinstance(raw_records, list):
                return
            for raw in raw_records:
                if not isinstance(raw, dict) or raw.get("success") is not True:
                    continue
                record = ProviderVerificationRecord(
                    provider=self._normalize_provider(raw.get("provider", "")),
                    configuration_fingerprint=str(
                        raw.get("configuration_fingerprint", "")
                    ),
                    success=True,
                    checked_at=float(raw.get("checked_at", 0)),
                    expires_at=float(raw.get("expires_at", 0)),
                    message="",
                    error_code=None,
                )
                if (
                    record.provider
                    and record.configuration_fingerprint
                    and math.isfinite(record.checked_at)
                    and math.isfinite(record.expires_at)
                    and record.checked_at <= record.expires_at
                    and record.checked_at <= now + _MAX_CLOCK_SKEW_SECONDS
                    and record.expires_at
                    <= record.checked_at + self._ttl_seconds
                    and now < record.expires_at
                ):
                    self._records[
                        (record.provider, record.configuration_fingerprint)
                    ] = record
            for provider in {key[0] for key in self._records}:
                self._prune_provider(provider, now=now)
            self._persist_successes()
        except FileNotFoundError:
            return
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable provider verification cache: %s", exc)

    def _persist_successes(self) -> bool:
        if self._storage_path is None:
            return True

        records = [
            {
                "provider": record.provider,
                "configuration_fingerprint": record.configuration_fingerprint,
                "success": True,
                "checked_at": record.checked_at,
                "expires_at": record.expires_at,
            }
            for record in sorted(
                self._records.values(),
                key=lambda item: (item.provider, item.checked_at),
            )
            if record.success
        ]
        temporary_path = self._storage_path.with_suffix(
            f"{self._storage_path.suffix}.tmp"
        )
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8") as persisted_cache:
                persisted_cache.write(
                    json.dumps(
                        {"version": _STORAGE_VERSION, "records": records},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                persisted_cache.flush()
                os.fsync(persisted_cache.fileno())
            os.replace(temporary_path, self._storage_path)
            self._revocation_path().unlink(missing_ok=True)
            return True
        except OSError as exc:
            logger.warning("Unable to persist provider verification cache: %s", exc)
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _persist_or_discard(self) -> None:
        """Durably revoke old successes before replacing the sanitized cache."""
        if self._storage_path is None:
            return
        temporary_path = self._storage_path.with_suffix(
            f"{self._storage_path.suffix}.tmp"
        )
        revocation_written = self._write_revocation_marker()
        if self._persist_successes():
            return

        cache_discarded = False
        try:
            self._storage_path.unlink(missing_ok=True)
            cache_discarded = True
        except OSError as exc:
            logger.error(
                "Unable to discard stale provider verification cache: %s",
                exc,
            )
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Unable to remove verification temp file: %s", exc)
        if not revocation_written and not cache_discarded:
            raise ProviderVerificationPersistenceError(
                "provider verification cache could not be durably revoked"
            )

    def _write_revocation_marker(self) -> bool:
        assert self._storage_path is not None
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with self._revocation_path().open("w", encoding="utf-8") as marker:
                marker.write("revoked\n")
                marker.flush()
                os.fsync(marker.fileno())
            return True
        except OSError as exc:
            logger.error(
                "Unable to write provider verification revocation marker: %s",
                exc,
            )
            return False

    def _revocation_path(self) -> Path:
        assert self._storage_path is not None
        return self._storage_path.with_suffix(
            f"{self._storage_path.suffix}.revoked"
        )

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("provider verification clock must return a finite value")
        return now

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


def _default_provider_verification_path() -> Path:
    override = os.environ.get("ASMR_HELPER_PROVIDER_VERIFICATION_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    state_override = os.environ.get("ASMR_HELPER_STATE_DB", "").strip()
    if state_override:
        state_path = Path(state_override).expanduser().resolve()
        return state_path.with_name(
            f"{state_path.name}.provider-verifications.json"
        )

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "AsmrHelper" / "provider-verifications.json"

    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "asmr-helper" / "provider-verifications.json"

    return (
        Path.home()
        / ".local"
        / "share"
        / "asmr-helper"
        / "provider-verifications.json"
    )


def get_provider_verification_registry() -> ProviderVerificationRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ProviderVerificationRegistry(
                    storage_path=_default_provider_verification_path()
                )
    return _registry
