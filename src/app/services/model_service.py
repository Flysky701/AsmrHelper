"""Application-layer wrapper for core model services."""

from __future__ import annotations

import threading

from src.core.resources import get_model_service as get_core_model_service

from ..dto import (
    ModelOperationResult,
    ModelStatusView,
    ModelSummary,
    ModelVerificationResult,
)
from ..errors import AppExecutionError, AppValidationError


class ModelService:
    """Stable application-facing facade for model operations."""

    def __init__(self, core_service=None):
        self.core_service = core_service or get_core_model_service()

    def list_models(self, kind: str | None = None, category: str | None = None) -> list[ModelSummary]:
        entries = self.core_service.list_models(kind=kind, category=category)
        return [
            ModelSummary(
                model_id=entry.id,
                kind=entry.kind,
                category=entry.category,
                backend=entry.provider or entry.engine or "-",
                display_name=entry.display_name,
            )
            for entry in entries
        ]

    def get_model_status(self, model_id: str) -> ModelStatusView:
        status = self._get_core_status(model_id)
        return ModelStatusView(
            model_id=status.model_id,
            status=status.status,
            detail=status.detail,
        )

    def list_model_statuses(
        self,
        kind: str | None = None,
        category: str | None = None,
    ) -> list[ModelStatusView]:
        try:
            statuses = self.core_service.get_all_statuses(kind=kind, category=category)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc
        return [
            ModelStatusView(
                model_id=status.model_id,
                status=status.status,
                detail=status.detail,
            )
            for status in statuses
        ]

    def install_model(
        self,
        model_id: str,
        mirror: str | None = None,
        force: bool = False,
    ) -> ModelOperationResult:
        return self._run_model_operation(
            action="install",
            model_id=model_id,
            runner=lambda: self.core_service.install(model_id, mirror=mirror, force=force),
        )

    def verify_models(self, model_id: str | None = None) -> list[ModelVerificationResult]:
        if model_id:
            entry = self._get_model_entry(model_id)
            if getattr(entry, "kind", None) == "cloud":
                status = self.get_model_status(model_id)
                return [
                    ModelVerificationResult(
                        model_id=model_id,
                        success=status.status == "configured",
                        status=status.status,
                        detail=status.detail,
                    )
                ]

        try:
            results = self.core_service.verify(model_id=model_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        verification_results: list[ModelVerificationResult] = []
        for current_id, ok in results.items():
            status = self.get_model_status(current_id)
            verification_results.append(
                ModelVerificationResult(
                    model_id=current_id,
                    success=bool(ok),
                    status=status.status,
                    detail=status.detail,
                )
            )
        return verification_results

    def remove_model(self, model_id: str) -> ModelOperationResult:
        return self._run_model_operation(
            action="remove",
            model_id=model_id,
            runner=lambda: self.core_service.remove(model_id),
        )

    def _get_model_entry(self, model_id: str):
        try:
            return self.core_service.get_model(model_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

    def _get_core_status(self, model_id: str):
        try:
            return self.core_service.get_status(model_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

    def _run_model_operation(self, action: str, model_id: str, runner) -> ModelOperationResult:
        self._get_model_entry(model_id)
        try:
            operation_result = runner()
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if operation_result is False:
            raise AppExecutionError(f"model {action} failed: {model_id}")

        status = self.get_model_status(model_id)
        return ModelOperationResult(
            action=action,
            model_id=model_id,
            success=True,
            status=status.status,
            detail=status.detail,
        )


_service: ModelService | None = None
_lock = threading.Lock()


def get_model_service() -> ModelService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ModelService()
    return _service
