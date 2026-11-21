"""Structured error contracts for stateless GPU compute operations.

Pure Pydantic v2 + Python stdlib only. Zero ML, HTTP, or database imports.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComputeErrorCode(StrEnum):
    """Canonical error codes across local subprocess and remote HTTP transports."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID = "AUTH_INVALID"
    INVALID_REQUEST = "INVALID_REQUEST"
    AUDIO_DECODE_ERROR = "AUDIO_DECODE_ERROR"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    LEASE_CONFLICT = "LEASE_CONFLICT"
    OOM_ERROR = "OOM_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"


class ComputeErrorPayload(BaseModel):
    """Serializable error payload returned by gpu-worker endpoints and CLI."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., min_length=1, description="Machine-readable error code.")
    message: str = Field(..., description="Human-readable error summary.")
    retryable: bool = Field(
        default=False,
        description="Whether retrying or reconnecting to another worker may succeed.",
    )
    stage: str = Field(
        default="unknown",
        min_length=1,
        description="Pipeline stage or subsystem where the failure occurred.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured diagnostic metadata.",
    )


class ComputeRemoteError(RuntimeError):
    """Exception raised when a local or remote GPU compute call fails."""

    def __init__(
        self,
        payload: ComputeErrorPayload | None = None,
        *,
        code: str = ComputeErrorCode.EXECUTION_ERROR,
        message: str = "Compute worker execution failed",
        retryable: bool = False,
        stage: str = "unknown",
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        if payload is None:
            payload = ComputeErrorPayload(
                code=code,
                message=message,
                retryable=retryable,
                stage=stage,
                details=dict(details or {}),
            )
        self.payload = payload
        self.status_code = status_code
        super().__init__(f"[{payload.code}] ({payload.stage}) {payload.message}")

    @property
    def code(self) -> str:
        return self.payload.code

    @property
    def message(self) -> str:
        return self.payload.message

    @property
    def retryable(self) -> bool:
        return self.payload.retryable

    @property
    def stage(self) -> str:
        return self.payload.stage

    @property
    def details(self) -> dict[str, Any]:
        return self.payload.details
