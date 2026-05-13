"""Application-layer wrapper for core model services."""

from __future__ import annotations

import threading

from src.core.resources import get_model_service as get_core_model_service

from ..dto import ModelStatusView, ModelSummary


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
        status = self.core_service.get_status(model_id)
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
        statuses = self.core_service.get_all_statuses(kind=kind, category=category)
        return [
            ModelStatusView(
                model_id=status.model_id,
                status=status.status,
                detail=status.detail,
            )
            for status in statuses
        ]


_service: ModelService | None = None
_lock = threading.Lock()


def get_model_service() -> ModelService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ModelService()
    return _service
