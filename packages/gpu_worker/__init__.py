"""Stateless GPU compute worker package (local subprocess + remote HTTP)."""

from .client import (
    ComputeClient,
    ComputeTransport,
    LocalSubprocessTransport,
    RemoteHttpTransport,
)
from .handlers import WorkerHandlers
from .server import create_worker_app
from .vram_lease import HardwareSnapshot, ModelLeaseManager, detect_gpu_hardware

__all__ = [
    "ComputeClient",
    "ComputeTransport",
    "LocalSubprocessTransport",
    "RemoteHttpTransport",
    "WorkerHandlers",
    "create_worker_app",
    "HardwareSnapshot",
    "ModelLeaseManager",
    "detect_gpu_hardware",
]
