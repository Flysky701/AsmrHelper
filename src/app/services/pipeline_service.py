"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.core.orchestration import (
    LegacyPipelineOrchestrator,
    PipelineExecutionContext,
    PipelineExecutionPlan,
    build_execution_plan,
)

from ..dto import ArtifactSet, PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError
from .artifact_service import ArtifactService, get_artifact_service
from .input_catalog_service import InputCatalogService, get_input_catalog_service
from .resource_service import ResourceService, get_resource_service
from .session_service import SessionService, get_session_service
from .task_service import TaskService, get_task_service
from .workspace_service import WorkspaceService, get_workspace_service


LANG_MAP = {
    "ja": ("日文", "中文"),
    "zh": ("中文", "英文"),
    "en": ("英文", "中文"),
}

SUPPORTED_LANGUAGE_CODES = frozenset(LANG_MAP)
PROGRESS_MESSAGE_DEFAULT = 0.1


def _get_step_errors(results: dict) -> dict[str, str]:
    step_errors: dict[str, str] = {}
    for step_name, step_result in results.get("steps", {}).items():
        if isinstance(step_result, dict) and step_result.get("error"):
            step_errors[step_name] = str(step_result["error"])
    return step_errors


class PipelineService:
    """Wrap core pipeline invocation behind stable request/result DTOs."""

    def __init__(
        self,
        task_service: TaskService | None = None,
        resource_service: ResourceService | None = None,
        workspace_service: WorkspaceService | None = None,
        input_catalog_service: InputCatalogService | None = None,
        session_service: SessionService | None = None,
        artifact_service: ArtifactService | None = None,
        orchestrator: LegacyPipelineOrchestrator | None = None,
    ) -> None:
        self._task_service = task_service or get_task_service()
        self._resource_service = resource_service or get_resource_service()
        self._workspace_service = workspace_service or get_workspace_service()
        self._input_catalog_service = input_catalog_service or get_input_catalog_service()
        self._session_service = session_service or get_session_service()
        self._artifact_service = artifact_service or get_artifact_service()
        self._orchestrator = orchestrator or LegacyPipelineOrchestrator()

    def run_audio_pipeline(self, request: PipelineRequest) -> PipelineResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        if request.source_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported source_lang: {request.source_lang}")
        if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported target_lang: {request.target_lang}")

        task_spec = self.create_pipeline_task_spec(request)
        return self.run_pipeline_task(task_spec.task_id)

    def run_pipeline_task(self, task_id: str) -> PipelineResult:
        task_spec = self._task_service.get_task_spec(task_id)
        if task_spec.task_type != "pipeline":
            raise AppValidationError(f"task is not a pipeline task: {task_id}")
        return self.run_pipeline_task_spec(task_spec)

    def run_pipeline_task_spec(self, task_spec) -> PipelineResult:
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        self._task_service.start_task(task_spec.task_id, message="running pipeline")

        try:
            workspace = self._resource_service.ensure_workspace()
            output_dir = session.resolved_output_dir or str(workspace["output_dir"])
            self._task_service.update_progress(
                task_spec.task_id,
                progress=0.1,
                message="preparing workspace",
            )

            pipeline_options = dict(task_spec.execution_profile.get("pipeline", {}))

            source_lang = pipeline_options.get("source_lang", "ja")
            target_lang = pipeline_options.get("target_lang", "zh")
            if source_lang not in SUPPORTED_LANGUAGE_CODES:
                raise AppValidationError(f"unsupported source_lang: {source_lang}")
            if target_lang not in SUPPORTED_LANGUAGE_CODES:
                raise AppValidationError(f"unsupported target_lang: {target_lang}")

            companion_vtt_path = self._resolve_companion_subtitle_path(session.companion_asset_ids)
            context = PipelineExecutionContext(
                task_id=task_spec.task_id,
                input_path=input_asset.absolute_path,
                output_dir=output_dir,
                source_lang=source_lang,
                target_lang=target_lang,
                companion_subtitle_path=companion_vtt_path,
                execution_profile=dict(task_spec.execution_profile),
            )

            def on_progress(message: str) -> None:
                self._task_service.update_progress(
                    task_spec.task_id,
                    progress=PROGRESS_MESSAGE_DEFAULT,
                    message=message,
                )

            results = self._orchestrator.run(
                context,
                progress_callback=on_progress,
            )
            step_errors = results.get("step_errors", {})
            if not step_errors:
                step_errors = _get_step_errors(results)
            if step_errors:
                detail = "; ".join(
                    f"{step_name}: {error_message}"
                    for step_name, error_message in step_errors.items()
                )
                raise AppExecutionError(f"pipeline reported step errors: {detail}")
        except Exception as exc:
            self._task_service.fail_task(
                task_spec.task_id,
                message="pipeline failed",
                detail=str(exc),
            )
            if isinstance(exc, (AppValidationError, AppExecutionError)):
                raise
            raise AppExecutionError(str(exc)) from exc

        self._task_service.update_progress(
            task_spec.task_id,
            progress=0.9,
            message="pipeline finished",
        )
        mix_path = results.get("mix_path")
        exported_subtitle = results.get("exported_subtitle")
        completed_task = self._task_service.complete_task(
            task_spec.task_id,
            message="pipeline completed",
            detail=mix_path or exported_subtitle or "",
        )
        self._register_pipeline_artifacts(
            task_id=task_spec.task_id,
            results=results,
            mix_path=mix_path,
            exported_subtitle=exported_subtitle,
        )

        return PipelineResult(
            success=True,
            input_path=results.get("input", input_asset.absolute_path),
            task=completed_task,
            task_id=completed_task.task_id,
            task_state=completed_task.state,
            artifacts=ArtifactSet.from_optional_paths(
                primary_output=mix_path or exported_subtitle,
                mix=mix_path,
                subtitle=exported_subtitle,
            ),
            mix_path=mix_path,
            exported_subtitle=exported_subtitle,
            steps=results.get("steps", {}),
            total_duration=float(results.get("total_duration", 0.0)),
            error_message=results.get("error"),
        )

    def list_presets(self) -> dict[str, str]:
        pipeline_class, _ = self._orchestrator._load_pipeline_runtime()
        return dict(getattr(pipeline_class, "PRESETS", {}))

    def build_plan(self, task_spec) -> PipelineExecutionPlan:
        """Build an execution plan from a task spec without running it.

        Useful for inspection, validation, or preview before execution.
        """
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        workspace = self._resource_service.ensure_workspace()
        output_dir = session.resolved_output_dir or str(workspace["output_dir"])

        pipeline_options = dict(task_spec.execution_profile.get("pipeline", {}))
        source_lang = pipeline_options.get("source_lang", "ja")
        target_lang = pipeline_options.get("target_lang", "zh")
        companion_vtt_path = self._resolve_companion_subtitle_path(session.companion_asset_ids)

        context = PipelineExecutionContext(
            task_id=task_spec.task_id,
            input_path=input_asset.absolute_path,
            output_dir=output_dir,
            source_lang=source_lang,
            target_lang=target_lang,
            companion_subtitle_path=companion_vtt_path,
            execution_profile=dict(task_spec.execution_profile),
        )
        return build_execution_plan(context)

    def create_pipeline_task_spec(
        self,
        request: PipelineRequest,
        *,
        task_source: str = "legacy-pipeline-route",
    ):
        workspace = self._workspace_service.resolve()
        inspected_assets = self._input_catalog_service.inspect_paths([request.input_path])
        primary_asset = inspected_assets[0]
        companion_asset_ids: list[str] = []
        if request.vtt_path:
            companion_assets = self._input_catalog_service.inspect_paths([request.vtt_path])
            companion_asset_ids = [asset.asset_id for asset in companion_assets]
        session = self._session_service.create_session(
            workspace_id=workspace.workspace_id,
            mode="single-audio",
            input_asset_ids=[primary_asset.asset_id],
            primary_input_asset_id=primary_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            output_policy={
                "mode": "custom-dir" if request.output_dir else "workspace-default",
                "custom_output_dir": request.output_dir or None,
            },
        )
        execution_profile = {
            "pipeline": {
                "source_lang": request.source_lang,
                "target_lang": request.target_lang,
                "use_vocal_separator": request.use_vocal_separator,
                "skip_existing": request.skip_existing,
                "output_mode": request.output_mode,
                "batch_root_dir": request.batch_root_dir,
            },
            "stages": {
                "separator": {
                    "provider": "builtin",
                    "model": request.vocal_model,
                },
                "asr": {
                    "provider": "faster_whisper",
                    "model": request.asr_model,
                    "common_options": {"language": request.source_lang},
                    "provider_options": {"disable_vad": True},
                },
                "llm": {
                    "provider": request.translate_provider,
                    "model": "default",
                    "common_options": {},
                    "provider_options": {},
                },
                "tts": {
                    "provider": request.tts_engine,
                    "model": "default",
                    "common_options": {"voice": request.tts_voice, "speed": request.tts_speed},
                    "provider_options": {"voice_profile_id": request.voice_profile_id},
                },
            },
            "mix": {
                "original_volume": request.original_volume,
                "tts_volume_ratio": request.tts_volume_ratio,
                "tts_delay": request.tts_delay,
            },
        }
        task_spec, _ = self._task_service.create_task_spec(
            task_type="pipeline",
            task_source=task_source,
            session_id=session.session_id,
            input_asset_id=primary_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            execution_profile=execution_profile,
        )
        return task_spec

    def _resolve_companion_subtitle_path(self, companion_asset_ids: list[str]) -> str | None:
        for asset_id in companion_asset_ids:
            asset = self._input_catalog_service.get_asset(asset_id)
            if asset.kind == "subtitle":
                return asset.absolute_path
        return None

    def _register_pipeline_artifacts(
        self,
        *,
        task_id: str,
        results: dict[str, Any],
        mix_path: str | None,
        exported_subtitle: str | None,
    ) -> None:
        if mix_path:
            self._artifact_service.register_artifact(
                task_id=task_id,
                artifact_type="audio.mix",
                path=mix_path,
                label="Mixed Output",
                preview_kind="audio",
                stage="mix",
                is_primary=True,
            )
        if exported_subtitle:
            self._artifact_service.register_artifact(
                task_id=task_id,
                artifact_type=f"subtitle.{Path(exported_subtitle).suffix.lstrip('.') or 'srt'}",
                path=exported_subtitle,
                label="Exported Subtitle",
                preview_kind="subtitle",
                stage="subtitle_export",
                is_primary=not bool(mix_path),
            )
        for file_key, stage_name, artifact_type, preview_kind in (
            ("vocal_path", "separation", "audio.vocals", "audio"),
            ("tts_audio_path", "tts", "audio.tts", "audio"),
            ("transcript_path", "asr", "text.transcript", "text"),
        ):
            path = results.get(file_key)
            if path:
                self._artifact_service.register_artifact(
                    task_id=task_id,
                    artifact_type=artifact_type,
                    path=path,
                    label=file_key,
                    preview_kind=preview_kind,
                    stage=stage_name,
                    is_primary=False,
                )


_service: PipelineService | None = None
_lock = threading.Lock()


def get_pipeline_service() -> PipelineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PipelineService()
    return _service
