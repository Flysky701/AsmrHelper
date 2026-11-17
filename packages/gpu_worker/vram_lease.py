"""Thread-safe GPU VRAM lease manager with LRU and stage-switch eviction.

Designed for 16GB-class GPUs (such as Google Colab Tesla T4 or RTX 4060 Ti / 4070 Ti)
where keeping Demucs, Whisper/FunASR, and local TTS resident simultaneously causes
CUDA OOM. Before loading a new heavy model when capacity is full or switching stages,
idle resident models are unloaded, Python garbage collection runs, and the PyTorch
CUDA allocator cache is emptied.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import gc
import logging
import threading
import time
from typing import Any, TypeVar

from packages.protocol.compute import DEFAULT_SUPPORTED_TASKS, WorkerCapabilities
from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

logger = logging.getLogger(__name__)

T = TypeVar("T")
LOW_VRAM_THRESHOLD_MB = 16384


@dataclass
class HardwareSnapshot:
    """Detected accelerator properties."""

    device: str = "cpu"
    device_name: str | None = None
    cuda_available: bool = False
    vram_total_mb: int = 0
    vram_free_mb: int | None = None


@dataclass
class _ResidentModel:
    key: str
    family: str
    heavy: bool
    instance: Any
    unload_fn: Callable[[Any], None] | None = None
    active_leases: int = 0


def detect_gpu_hardware() -> HardwareSnapshot:
    """Probe CUDA device metadata safely without requiring PyTorch at import time."""
    try:
        import torch

        if not torch.cuda.is_available():
            return HardwareSnapshot()

        idx = int(torch.cuda.current_device())
        props = torch.cuda.get_device_properties(idx)
        total_mb = int(props.total_memory // (1024 * 1024))
        free_mb: int | None = None
        try:
            free_bytes, _total_bytes = torch.cuda.mem_get_info(idx)
            free_mb = int(free_bytes // (1024 * 1024))
        except Exception:
            try:
                reserved = int(torch.cuda.memory_reserved(idx))
                free_mb = max(0, int((props.total_memory - reserved) // (1024 * 1024)))
            except Exception:
                free_mb = None

        return HardwareSnapshot(
            device=f"cuda:{idx}",
            device_name=str(getattr(props, "name", "")) or None,
            cuda_available=True,
            vram_total_mb=total_mb,
            vram_free_mb=free_mb,
        )
    except Exception:
        return HardwareSnapshot()


def default_cuda_cleanup() -> None:
    """Flush PyTorch CUDA caching allocator if torch + CUDA are present."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


class ModelLeaseManager:
    """Manages resident ML models with thread-safe leases and LRU/stage eviction."""

    def __init__(
        self,
        *,
        max_heavy_models: int | None = None,
        vram_total_mb: int | None = None,
        low_vram_threshold_mb: int = LOW_VRAM_THRESHOLD_MB,
        evict_on_stage_switch: bool | None = None,
        cuda_cleanup_fn: Callable[[], None] | None = None,
    ) -> None:
        hw = detect_gpu_hardware()
        effective_vram = hw.vram_total_mb if vram_total_mb is None else max(0, int(vram_total_mb))
        self._vram_override_mb = vram_total_mb
        self._low_vram_threshold_mb = max(0, int(low_vram_threshold_mb))

        is_constrained_gpu = effective_vram <= self._low_vram_threshold_mb
        if max_heavy_models is None:
            resolved_max = 1 if is_constrained_gpu else 2
        else:
            if max_heavy_models < 1:
                raise ValueError("max_heavy_models must be >= 1")
            resolved_max = int(max_heavy_models)

        if evict_on_stage_switch is None:
            # On <=16GB GPUs (e.g. Colab T4), default to keeping only 1 heavy model family
            # resident; if caller explicitly configured max_heavy_models > 1, allow multi-family LRU.
            resolved_stage_evict = is_constrained_gpu and resolved_max == 1
        else:
            resolved_stage_evict = bool(evict_on_stage_switch)

        self._max_heavy_models = resolved_max
        self._evict_on_stage_switch = resolved_stage_evict
        self._cuda_cleanup_fn = cuda_cleanup_fn
        self._entries: OrderedDict[str, _ResidentModel] = OrderedDict()
        self._cond = threading.Condition(threading.Lock())
        self._loading_heavy = False

    @property
    def max_heavy_models(self) -> int:
        return self._max_heavy_models

    @property
    def evict_on_stage_switch(self) -> bool:
        return self._evict_on_stage_switch

    def loaded_models(self) -> list[str]:
        """Return currently resident model keys in LRU -> MRU order."""
        with self._cond:
            return list(self._entries.keys())

    def capabilities(
        self, supported_tasks: list[str] | None = None
    ) -> WorkerCapabilities:
        """Build a `WorkerCapabilities` snapshot reflecting current hardware & leases."""
        hw = detect_gpu_hardware()
        vram_mb = (
            hw.vram_total_mb
            if self._vram_override_mb is None
            else max(0, int(self._vram_override_mb))
        )
        return WorkerCapabilities(
            device=hw.device,
            device_name=hw.device_name,
            cuda_available=hw.cuda_available,
            vram_total_mb=vram_mb,
            vram_free_mb=hw.vram_free_mb,
            loaded_models=self.loaded_models(),
            supported_tasks=list(supported_tasks or DEFAULT_SUPPORTED_TASKS),
        )

    def _select_victims_locked(self, incoming_family: str) -> list[_ResidentModel]:
        """Select resident heavy entries that must be evicted before loading a new heavy model."""
        heavy_entries = [e for e in self._entries.values() if e.heavy]
        if not heavy_entries:
            return []

        victims_by_key: OrderedDict[str, _ResidentModel] = OrderedDict()
        if self._evict_on_stage_switch:
            for entry in heavy_entries:
                if entry.family != incoming_family:
                    victims_by_key[entry.key] = entry

        remaining = [e for e in heavy_entries if e.key not in victims_by_key]
        while len(remaining) >= self._max_heavy_models:
            oldest = remaining.pop(0)
            victims_by_key[oldest.key] = oldest

        return list(victims_by_key.values())

    def _run_cleanup(self, evicted_entries: list[_ResidentModel]) -> None:
        """Unload model instances, run GC, and release CUDA cached blocks."""
        for entry in evicted_entries:
            instance = entry.instance
            entry.instance = None
            if instance is None:
                continue
            try:
                if entry.unload_fn is not None:
                    entry.unload_fn(instance)
                elif hasattr(instance, "unload") and callable(instance.unload):
                    instance.unload()
            except Exception as exc:
                logger.warning("Error while unloading model %s: %s", entry.key, exc)
            finally:
                del instance

        gc.collect()
        default_cuda_cleanup()
        if self._cuda_cleanup_fn is not None:
            self._cuda_cleanup_fn()

    @contextmanager
    def lease(
        self,
        key: str,
        loader: Callable[[], T],
        *,
        family: str = "default",
        heavy: bool = True,
        unload_fn: Callable[[Any], None] | None = None,
        timeout: float = 300.0,
    ) -> Iterator[T]:
        """Acquire a thread-safe lease on `key`, evicting older heavy models if needed."""
        deadline = time.monotonic() + max(0.01, float(timeout))
        entry: _ResidentModel | None = None
        victims: list[_ResidentModel] = []
        need_load = False

        with self._cond:
            while True:
                if key in self._entries and not self._loading_heavy:
                    entry = self._entries[key]
                    self._entries.move_to_end(key)
                    entry.active_leases += 1
                    break

                if not heavy and key not in self._entries and not self._loading_heavy:
                    need_load = True
                    break

                if heavy and not self._loading_heavy:
                    candidate_victims = self._select_victims_locked(family)
                    if all(v.active_leases == 0 for v in candidate_victims):
                        for v in candidate_victims:
                            self._entries.pop(v.key, None)
                        victims = candidate_victims
                        self._loading_heavy = True
                        need_load = True
                        break

                remaining_wait = deadline - time.monotonic()
                if remaining_wait <= 0:
                    raise ComputeRemoteError(
                        code=ComputeErrorCode.LEASE_CONFLICT,
                        message=f"Timed out waiting for GPU VRAM lease for {key!r}",
                        retryable=True,
                        stage=family,
                    )
                self._cond.wait(timeout=remaining_wait)

        if need_load:
            try:
                if victims:
                    self._run_cleanup(victims)
                loaded_instance = loader()
            except Exception:
                with self._cond:
                    if heavy:
                        self._loading_heavy = False
                    self._cond.notify_all()
                raise

            with self._cond:
                entry = _ResidentModel(
                    key=key,
                    family=family,
                    heavy=heavy,
                    instance=loaded_instance,
                    unload_fn=unload_fn,
                    active_leases=1,
                )
                self._entries[key] = entry
                self._entries.move_to_end(key)
                if heavy:
                    self._loading_heavy = False
                self._cond.notify_all()

        assert entry is not None
        try:
            yield entry.instance
        finally:
            with self._cond:
                entry.active_leases = max(0, entry.active_leases - 1)
                self._cond.notify_all()

    def evict(
        self,
        family: str | None = None,
        *,
        key: str | None = None,
        timeout: float = 60.0,
    ) -> list[str]:
        """Explicitly evict idle models matching `family` / `key` (or all if omitted)."""
        deadline = time.monotonic() + max(0.01, float(timeout))
        victims: list[_ResidentModel] = []

        with self._cond:
            while True:
                targets = [
                    e
                    for e in self._entries.values()
                    if (family is None or e.family == family)
                    and (key is None or e.key == key)
                ]
                if not self._loading_heavy and all(t.active_leases == 0 for t in targets):
                    for t in targets:
                        self._entries.pop(t.key, None)
                    victims = targets
                    break

                remaining_wait = deadline - time.monotonic()
                if remaining_wait <= 0:
                    raise ComputeRemoteError(
                        code=ComputeErrorCode.LEASE_CONFLICT,
                        message="Cannot evict model while an active inference lease is held",
                        retryable=True,
                        stage=family or "lease",
                    )
                self._cond.wait(timeout=remaining_wait)

        evicted_keys = [v.key for v in victims]
        self._run_cleanup(victims)
        return evicted_keys
