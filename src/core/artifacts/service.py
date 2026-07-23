"""Core artifact indexing service."""

from __future__ import annotations

from typing import Any

from .models import ArtifactRecord, ArtifactSet


class ArtifactIndex:
    """Track task artifacts and build lightweight result views."""

    def __init__(self) -> None:
        self._task_artifacts: dict[str, ArtifactSet] = {}
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._counter = 0

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
            raise ValueError("task_id is required")
        if not path:
            raise ValueError("path is required")

        self._counter += 1
        artifact_id = f"artifact-{self._counter}"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            task_id=task_id,
            artifact_type=artifact_type,
            path=path,
            label=label or artifact_type,
            preview_kind=preview_kind,
            stage=stage,
            is_primary=is_primary,
            metadata=dict(metadata or {}),
        )
        current = self._task_artifacts.get(task_id, ArtifactSet())
        updated_entries = list(current.entries) + [record]
        updated_files = dict(current.files)
        file_key = self._artifact_type_to_key(artifact_type)
        if file_key:
            updated_files[file_key] = path
        primary_output = path if is_primary or not current.primary_output else current.primary_output
        updated = ArtifactSet(
            files=updated_files,
            primary_output=primary_output,
            entries=updated_entries,
        )
        self._task_artifacts[task_id] = updated
        self._artifacts[artifact_id] = record
        return self.clone_record(record)

    def restore_artifact(self, record: ArtifactRecord) -> None:
        if not record.artifact_id:
            raise ValueError("artifact_id is required")
        if not record.task_id:
            raise ValueError("task_id is required")
        if not record.path:
            raise ValueError("path is required")
        if record.artifact_id in self._artifacts:
            return

        current = self._task_artifacts.get(record.task_id, ArtifactSet())
        updated_files = dict(current.files)
        file_key = self._artifact_type_to_key(record.artifact_type)
        if file_key:
            updated_files[file_key] = record.path
        self._task_artifacts[record.task_id] = ArtifactSet(
            files=updated_files,
            primary_output=(
                record.path
                if record.is_primary or not current.primary_output
                else current.primary_output
            ),
            entries=list(current.entries) + [self.clone_record(record)],
        )
        self._artifacts[record.artifact_id] = self.clone_record(record)

        prefix, separator, suffix = record.artifact_id.rpartition("-")
        if separator and prefix == "artifact" and suffix.isdigit():
            self._counter = max(self._counter, int(suffix))

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        try:
            record = self._artifacts[artifact_id]
        except KeyError as exc:
            raise ValueError(f"unknown artifact id: {artifact_id}") from exc
        return self.clone_record(record)

    def get_task_artifacts(self, task_id: str) -> ArtifactSet:
        artifact_set = self._task_artifacts.get(task_id, ArtifactSet())
        return self.clone_artifact_set(artifact_set)

    def get_task_result_view(self, task_id: str) -> dict[str, Any]:
        artifact_set = self.get_task_artifacts(task_id)
        primary_record = next(
            (entry for entry in artifact_set.entries if entry.is_primary),
            artifact_set.entries[0] if artifact_set.entries else None,
        )
        return {
            "task_id": task_id,
            "primary_artifact_id": (
                primary_record.artifact_id if primary_record is not None else None
            ),
            "artifacts": [
                self.clone_record(entry)
                for entry in artifact_set.entries
            ],
            "warnings": [],
        }

    def get_task_preview_view(self, task_id: str) -> dict[str, Any]:
        result = self.get_task_result_view(task_id)
        artifacts = result["artifacts"]
        preview_modes: list[str] = []
        for entry in artifacts:
            if entry.preview_kind and entry.preview_kind not in preview_modes:
                preview_modes.append(entry.preview_kind)
        return {
            "task_id": task_id,
            "primary_artifact_id": result["primary_artifact_id"],
            "artifacts": artifacts,
            "warnings": list(result["warnings"]),
            "preview_modes": preview_modes,
            "artifact_count": len(artifacts),
        }

    @staticmethod
    def _artifact_type_to_key(artifact_type: str) -> str:
        mapping = {
            "audio.mix": "mix",
            "audio.tts": "tts_audio",
            "audio.vocals": "vocals",
            "subtitle.srt": "subtitle",
            "subtitle.vtt": "subtitle",
            "subtitle.lrc": "subtitle",
            "text.transcript": "transcript",
        }
        return mapping.get(artifact_type, artifact_type.replace(".", "_"))

    @staticmethod
    def clone_record(record: ArtifactRecord | None) -> ArtifactRecord | None:
        if record is None:
            return None
        return ArtifactRecord(
            artifact_id=record.artifact_id,
            task_id=record.task_id,
            artifact_type=record.artifact_type,
            path=record.path,
            label=record.label,
            preview_kind=record.preview_kind,
            stage=record.stage,
            is_primary=record.is_primary,
            metadata=dict(record.metadata),
        )

    def clone_artifact_set(self, artifact_set: ArtifactSet) -> ArtifactSet:
        return ArtifactSet(
            files=dict(artifact_set.files),
            primary_output=artifact_set.primary_output,
            entries=[self.clone_record(entry) for entry in artifact_set.entries if entry is not None],
        )
