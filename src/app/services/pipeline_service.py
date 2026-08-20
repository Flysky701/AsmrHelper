"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading
import logging
from pathlib import Path
from typing import Any

from src.core.orchestration import (
    PipelineExecutionContext,
    PipelineExecutionPlan,
    PipelineExecutor,
    build_execution_plan,
)
from src.utils import sanitize_filename

from ..dto import ArtifactSet, PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError, ResourceValidationError
from .artifact_service import ArtifactService, get_artifact_service
from .input_catalog_service import InputCatalogService, get_input_catalog_service
from .preset_catalog_service import get_preset_catalog_service
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
logger = logging.getLogger(__name__)
STAGE_ALIASES = {
    "vocal_separator": "separate",
    "mixer": "mix",
    "subtitle": "export",
}


def _build_pipeline_task_error(stage: str, detail: str) -> dict[str, object]:
    normalized = detail.lower()
    if "no module named" in normalized:
        code = "PROVIDER_DEPENDENCY_MISSING"
    elif stage == "tts" and "no audio" in normalized:
        code = "PROVIDER_RESPONSE_INVALID"
    elif stage == "translate":
        code = "PROVIDER_EXECUTION_FAILED"
    else:
        code = "TASK_EXECUTION_FAILED"
    error: dict[str, object] = {
        "code": code,
        "stage": stage,
        "message": f"{stage} failed: {detail}",
        "retryable": True,
        "detail": detail,
    }
    if code == "PROVIDER_EXECUTION_FAILED":
        error.update(
            {
                "action": "settings",
                "suggestion": "请在设置中主动验证服务连接，确认无误后重试任务",
            }
        )
    return error


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
        executor: PipelineExecutor | None = None,
    ) -> None:
        self._task_service = task_service or get_task_service()
        self._resource_service = resource_service or get_resource_service()
        self._workspace_service = workspace_service or get_workspace_service()
        self._input_catalog_service = input_catalog_service or get_input_catalog_service()
        self._session_service = session_service or get_session_service()
        self._artifact_service = artifact_service or get_artifact_service()
        self._executor = executor or PipelineExecutor()

    def run_audio_pipeline(
        self,
        request: PipelineRequest,
        *,
        progress_callback=None,
        cancel_event=None,
    ) -> PipelineResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        if request.source_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported source_lang: {request.source_lang}")
        if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported target_lang: {request.target_lang}")

        _task, task_spec = self.create_pipeline_task(request)
        from .pipeline_task_orchestrator import PipelineTaskOrchestrator

        orchestrator = PipelineTaskOrchestrator(
            pipeline_service=self,
            task_service=self._task_service,
            artifact_service=self._artifact_service,
        )
        return orchestrator.run_task(
            task_spec.task_id,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    def run_pipeline_task(
        self,
        task_id: str,
        *,
        progress_callback=None,
        cancel_event=None,
        manage_lifecycle: bool = True,
    ) -> PipelineResult:
        task_spec = self._task_service.get_task_spec(task_id)
        if task_spec.task_type != "pipeline":
            raise AppValidationError(f"task is not a pipeline task: {task_id}")
        return self.run_pipeline_task_spec(
            task_spec,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            manage_lifecycle=manage_lifecycle,
        )

    def run_pipeline_task_spec(
        self,
        task_spec,
        *,
        progress_callback=None,
        cancel_event=None,
        manage_lifecycle: bool = True,
    ) -> PipelineResult:
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        current_stage = "prepare"
        failure_error: dict[str, object] | None = None
        if manage_lifecycle:
            self._task_service.start_task(
                task_spec.task_id,
                message="running pipeline",
                stage=current_stage,
            )

        try:
            self._assert_task_ready(
                task_spec.execution_profile,
                input_path=input_asset.absolute_path,
            )
            workspace = self._resource_service.ensure_workspace()
            execution_profile = dict(task_spec.execution_profile)
            output_dir = self._resolve_task_output_dir(
                task_id=task_spec.task_id,
                input_path=input_asset.absolute_path,
                execution_profile=execution_profile,
                session_output_root=session.resolved_output_dir,
                workspace_output_root=str(workspace["output_dir"]),
            )
            if execution_profile.get("output_mode") == "batch":
                execution_profile["batch_root_dir"] = output_dir
            self._task_service.update_progress(
                task_spec.task_id,
                progress=0.1,
                message="preparing workspace",
            )

            source_lang, target_lang = self._resolve_profile_languages(
                execution_profile
            )
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
                execution_profile=execution_profile,
            )

            def on_progress(message: str) -> None:
                self._task_service.update_progress(
                    task_spec.task_id,
                    progress=PROGRESS_MESSAGE_DEFAULT,
                    message=message,
                )
                if progress_callback is not None:
                    progress_callback(message)

            def on_stage(stage: str, progress: float, message: str) -> None:
                nonlocal current_stage
                current_stage = stage
                self._task_service.update_progress(
                    task_spec.task_id,
                    progress=progress,
                    message=message,
                    stage=stage,
                )

            plan = build_execution_plan(context)
            results = self._executor.execute(
                plan,
                progress_callback=on_progress,
                stage_callback=on_stage,
                cancel_event=cancel_event,
            )

            step_errors = results.get("step_errors", {})
            if step_errors:
                failed_step, failed_detail = next(iter(step_errors.items()))
                current_stage = STAGE_ALIASES.get(failed_step, failed_step)
                failure_error = _build_pipeline_task_error(
                    current_stage,
                    str(failed_detail),
                )
                logger.error(
                    "Pipeline task %s failed at stage %s: %s",
                    task_spec.task_id,
                    current_stage,
                    failed_detail,
                )
                if not manage_lifecycle:
                    self._task_service.update_progress(
                        task_spec.task_id,
                        progress=self._task_service.get_task(task_spec.task_id).progress,
                        stage=current_stage,
                    )
                error = AppExecutionError(str(failure_error["message"]))
                error.task_error = failure_error
                raise error
        except Exception as exc:
            is_cancelled = (
                (cancel_event is not None and cancel_event.is_set())
                or "用户取消" in str(exc)
                or "cancel" in str(exc).lower()
            )
            if is_cancelled and manage_lifecycle:
                self._task_service.cancel_task(
                    task_spec.task_id,
                    message="cancelled by user",
                )
            elif manage_lifecycle:
                task_error = failure_error or _build_pipeline_task_error(
                    current_stage,
                    str(exc),
                )
                logger.exception(
                    "Pipeline task %s failed at stage %s",
                    task_spec.task_id,
                    current_stage,
                )
                self._task_service.fail_task(
                    task_spec.task_id,
                    message=str(task_error["message"]),
                    detail=str(task_error["detail"]),
                    stage=current_stage,
                    error=task_error,
                )
            if isinstance(
                exc,
                (AppValidationError, AppExecutionError, ResourceValidationError),
            ):
                raise
            raise AppExecutionError(str(exc)) from exc

        self._task_service.update_progress(
            task_spec.task_id,
            progress=0.9,
            message="pipeline finished",
        )
        mix_path = results.get("mix_path")
        exported_subtitle = results.get("exported_subtitle")
        primary_output = results.get("primary_output") or mix_path or exported_subtitle
        self._register_pipeline_artifacts(
            task_id=task_spec.task_id,
            results=results,
            mix_path=mix_path,
            exported_subtitle=exported_subtitle,
        )
        completed_task = (
            self._task_service.complete_task(
                task_spec.task_id,
                message="pipeline completed",
                detail=primary_output or "",
                stage="export",
                artifact_set_id=task_spec.task_id,
            )
            if manage_lifecycle
            else self._task_service.get_task(task_spec.task_id)
        )

        return PipelineResult(
            success=True,
            input_path=results.get("input", input_asset.absolute_path),
            task=completed_task,
            task_id=completed_task.task_id,
            task_state=completed_task.state,
            artifacts=ArtifactSet.from_optional_paths(
                primary_output=primary_output,
                mix=mix_path,
                subtitle=exported_subtitle,
            ),
            mix_path=mix_path,
            exported_subtitle=exported_subtitle,
            steps=results.get("steps", {}),
            total_duration=float(results.get("total_duration", 0.0)),
            error_message=results.get("error"),
        )

    def create_pipeline_task(
        self,
        request: PipelineRequest,
        *,
        task_source: str = "pipeline-create-route",
    ):
        """Create a pipeline task without blocking on its execution."""
        if not request.input_path:
            raise AppValidationError("input_path is required")
        if request.source_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported source_lang: {request.source_lang}")
        if request.target_lang not in SUPPORTED_LANGUAGE_CODES:
            raise AppValidationError(f"unsupported target_lang: {request.target_lang}")

        execution_profile = self._resolve_execution_profile(request)
        self._assert_task_ready(
            execution_profile,
            input_path=request.input_path,
        )
        task_spec = self.create_pipeline_task_spec(request, task_source=task_source)
        return self._task_service.get_task(task_spec.task_id), task_spec

    def _assert_task_ready(
        self,
        execution_profile: dict[str, Any],
        *,
        input_path: str | None = None,
    ) -> None:
        """Apply the backend-authoritative readiness gate for V1 pipeline profiles."""
        if execution_profile.get("version") != 1:
            raise AppValidationError(
                "pipeline execution profile must use StageProfile version 1"
            )
        readiness = self._resource_service.check_task_readiness(
            task_type="pipeline",
            execution_profile=execution_profile,
            input_path=input_path,
        )
        if readiness.get("ready") is not False:
            return
        issues = list(readiness.get("issues") or [])
        details = "; ".join(
            f"{issue.get('stage', 'prepare')}: "
            f"{issue.get('message', issue.get('requirement', 'not ready'))}"
            for issue in issues
        )
        if not details:
            details = ", ".join(readiness.get("missing_requirements") or [])
        raise ResourceValidationError(
            f"pipeline readiness check failed: {details or 'pipeline is not ready'}"
        )

    def list_presets(self) -> list[dict[str, Any]]:
        """Compatibility facade for callers that still use PipelineService."""
        return get_preset_catalog_service().list_presets()

    def build_plan(self, task_spec) -> PipelineExecutionPlan:
        """Build an execution plan from a task spec without running it.

        Useful for inspection, validation, or preview before execution.
        """
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        workspace = self._resource_service.ensure_workspace()
        execution_profile = dict(task_spec.execution_profile)
        output_dir = self._resolve_task_output_dir(
            task_id=task_spec.task_id,
            input_path=input_asset.absolute_path,
            execution_profile=execution_profile,
            session_output_root=session.resolved_output_dir,
            workspace_output_root=str(workspace["output_dir"]),
        )
        if execution_profile.get("output_mode") == "batch":
            execution_profile["batch_root_dir"] = output_dir

        source_lang, target_lang = self._resolve_profile_languages(
            execution_profile
        )
        companion_vtt_path = self._resolve_companion_subtitle_path(session.companion_asset_ids)

        context = PipelineExecutionContext(
            task_id=task_spec.task_id,
            input_path=input_asset.absolute_path,
            output_dir=output_dir,
            source_lang=source_lang,
            target_lang=target_lang,
            companion_subtitle_path=companion_vtt_path,
            execution_profile=execution_profile,
        )
        return build_execution_plan(context)

    def create_pipeline_task_spec(
        self,
        request: PipelineRequest,
        *,
        task_source: str = "pipeline-service",
    ):
        workspace = self._workspace_service.resolve()
        inspected_assets = self._input_catalog_service.inspect_paths([request.input_path])
        primary_asset = inspected_assets[0]
        companion_paths = list(request.companion_paths)
        if request.vtt_path and request.vtt_path not in companion_paths:
            companion_paths.append(request.vtt_path)
        companion_asset_ids: list[str] = []
        if companion_paths:
            companion_assets = self._input_catalog_service.inspect_paths(companion_paths)
            companion_asset_ids = [asset.asset_id for asset in companion_assets]
        session = self._session_service.create_session(
            workspace_id=workspace.workspace_id,
            mode="single-audio",
            input_asset_ids=[primary_asset.asset_id],
            primary_input_asset_id=primary_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            output_policy={
                "mode": "task-scoped-root",
                "custom_output_dir": request.output_dir or None,
            },
        )
        execution_profile = self._resolve_execution_profile(request)
        task_spec, _ = self._task_service.create_task_spec(
            task_type="pipeline",
            task_source=task_source,
            session_id=session.session_id,
            input_asset_id=primary_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            execution_profile=execution_profile,
        )
        return task_spec

    @staticmethod
    def _resolve_task_output_dir(
        *,
        task_id: str,
        input_path: str,
        execution_profile: dict[str, Any],
        session_output_root: str,
        workspace_output_root: str,
    ) -> str:
        """Return the non-overlapping TaskName/Filename output directory."""
        if (
            execution_profile.get("output_mode") == "batch"
            and execution_profile.get("batch_root_dir")
        ):
            root = Path(str(execution_profile["batch_root_dir"]))
        else:
            root = Path(session_output_root or workspace_output_root)
        safe_task_name = sanitize_filename(str(task_id).strip()) or "task"
        safe_filename = sanitize_filename(Path(input_path).stem) or "input"
        return str(root / safe_task_name / safe_filename)

    @staticmethod
    def _resolve_execution_profile(request: PipelineRequest) -> dict[str, Any]:
        if request.execution_profile:
            profile = dict(request.execution_profile)
            if profile.get("version") != 1 or not isinstance(
                profile.get("stages"), dict
            ):
                raise AppValidationError(
                    "pipeline execution profile must use StageProfile version 1"
                )
            return profile

        return {
            "version": 1,
            "source_lang": request.source_lang,
            "target_lang": request.target_lang,
            "skip_existing": request.skip_existing,
            # Internal batch layout metadata. Public HTTP schemas forbid these
            # fields, so they cannot become a second client contract.
            "output_mode": request.output_mode,
            "batch_root_dir": request.batch_root_dir,
            "stages": {
                "separate": {
                    "enabled": request.use_vocal_separator,
                    "provider": "demucs",
                    "model": request.vocal_model,
                    "options": {"mode": "vocals"},
                    "provider_options": {},
                },
                "asr": {
                    "enabled": True,
                    "provider": "faster_whisper",
                    "model": request.asr_model,
                    "options": {
                        "language": request.source_lang,
                        "output_format": "segments",
                        "timestamps": True,
                    },
                    "provider_options": {"vad_filter": False},
                },
                "translate": {
                    "enabled": request.source_lang != request.target_lang,
                    "provider": request.translate_provider,
                    "model": request.translate_model or None,
                    "options": {
                        "source_lang": request.source_lang,
                        "target_lang": request.target_lang,
                        "preserve_timestamps": True,
                    },
                    "provider_options": {},
                },
                "tts": {
                    "enabled": True,
                    "provider": request.tts_engine,
                    "model": None,
                    "options": {
                        "voice": request.tts_voice,
                        "voice_profile_id": request.voice_profile_id,
                        "speed": request.tts_speed,
                        "language": request.target_lang,
                    },
                    "provider_options": {
                        **request.engine_params.get(request.tts_engine, {}),
                    },
                },
                "mix": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {
                        "original_volume": request.original_volume,
                        "tts_volume_ratio": request.tts_volume_ratio,
                        "tts_delay_ms": request.tts_delay * 1000,
                        "normalize": True,
                    },
                    "provider_options": {},
                },
                "export": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {
                        "subtitle_format": "srt",
                        "include_intermediate_files": True,
                    },
                    "provider_options": {},
                },
            },
        }

    def _resolve_companion_subtitle_path(self, companion_asset_ids: list[str]) -> str | None:
        for asset_id in companion_asset_ids:
            asset = self._input_catalog_service.get_asset(asset_id)
            if asset.kind == "subtitle":
                return asset.absolute_path
        return None

    @staticmethod
    def _resolve_profile_languages(execution_profile: dict[str, Any]) -> tuple[str, str]:
        if execution_profile.get("version") == 1:
            return (
                str(execution_profile.get("source_lang", "ja")),
                str(execution_profile.get("target_lang", "zh")),
            )
        raise AppValidationError(
            "pipeline execution profile must use StageProfile version 1"
        )

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
