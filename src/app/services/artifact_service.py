"""Application-layer artifact indexing service."""

from __future__ import annotations

import threading
from typing import Any

from src.core.artifacts import ArtifactIndex, ArtifactRecord, ArtifactSet
from ..errors import AppValidationError


class ArtifactService:
    """Track task artifacts and lightweight result views in memory."""

    def __init__(self) -> None:
        self._index = ArtifactIndex()
        self._lock = threading.Lock()

    def register_artifact(
        self,
        *,
        task_id: str,
        artifact_type: str,
        path: str,
        label: str = "",
        preview_kind: str = "",
        stage: str = "",
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        if not task_id:
            raise AppValidationError("task_id is required")
        if not path:
            raise AppValidationError("path is required")

        with self._lock:
            try:
                return self._index.register_artifact(
                    task_id=task_id,
                    artifact_type=artifact_type,
                    path=path,
                    label=label,
                    preview_kind=preview_kind,
                    stage=stage,
                    is_primary=is_primary,
                    metadata=metadata,
                )
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with self._lock:
            try:
                return self._index.get_artifact(artifact_id)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

    def get_task_artifacts(self, task_id: str) -> ArtifactSet:
        with self._lock:
            return self._index.get_task_artifacts(task_id)

    def get_task_result_view(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return self._index.get_task_result_view(task_id)

    def get_task_preview_view(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return self._index.get_task_preview_view(task_id)


_service: ArtifactService | None = None
_lock = threading.Lock()


def get_artifact_service() -> ArtifactService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ArtifactService()
    return _service
