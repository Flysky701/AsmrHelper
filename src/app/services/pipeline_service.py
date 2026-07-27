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

from ..dto import ArtifactSet, PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError, ResourceValidationError
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
    else:
        code = "TASK_EXECUTION_FAILED"
    return {
        "code": code,
        "stage": stage,
        "message": f"{stage} failed: {detail}",
        "retryable": True,
        "detail": detail,
    }


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

        task_spec = self.create_pipeline_task_spec(request)
        return self.run_pipeline_task_spec(
            task_spec,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    def run_pipeline_task(
        self,
        task_id: str,
        *,
        progress_callback=None,
        cancel_event=None,
    ) -> PipelineResult:
        task_spec = self._task_service.get_task_spec(task_id)
        if task_spec.task_type != "pipeline":
            raise AppValidationError(f"task is not a pipeline task: {task_id}")
        return self.run_pipeline_task_spec(
            task_spec,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    def run_pipeline_task_spec(
        self,
        task_spec,
        *,
        progress_callback=None,
        cancel_event=None,
    ) -> PipelineResult:
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        current_stage = "prepare"
        failure_error: dict[str, object] | None = None
        self._task_service.start_task(
            task_spec.task_id,
            message="running pipeline",
            stage=current_stage,
        )

        try:
            self._assert_task_ready(task_spec.execution_profile)
            workspace = self._resource_service.ensure_workspace()
            output_dir = session.resolved_output_dir or str(workspace["output_dir"])
            self._task_service.update_progress(
                task_spec.task_id,
                progress=0.1,
                message="preparing workspace",
            )

            source_lang, target_lang = self._resolve_profile_languages(
                task_spec.execution_profile
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
                execution_profile=dict(task_spec.execution_profile),
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
                raise AppExecutionError(str(failure_error["message"]))
        except Exception as exc:
            is_cancelled = (
                (cancel_event is not None and cancel_event.is_set())
                or "用户取消" in str(exc)
                or "cancel" in str(exc).lower()
            )
            if is_cancelled:
                self._task_service.cancel_task(
                    task_spec.task_id,
                    message="cancelled by user",
                )
            else:
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
        completed_task = self._task_service.complete_task(
            task_spec.task_id,
            message="pipeline completed",
            detail=primary_output or "",
            stage="export",
            artifact_set_id=task_spec.task_id,
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

        self._assert_task_ready(request.execution_profile)
        task_spec = self.create_pipeline_task_spec(request, task_source=task_source)
        return self._task_service.get_task(task_spec.task_id), task_spec

    def _assert_task_ready(self, execution_profile: dict[str, Any]) -> None:
        """Apply the backend-authoritative readiness gate for V1 pipeline profiles."""
        if execution_profile.get("version") != 1:
            return
        readiness = self._resource_service.check_task_readiness(
            task_type="pipeline",
            execution_profile=execution_profile,
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
        """Load presets from config/presets.yaml."""
        import yaml

        from src.config import PROJECT_ROOT

        presets_path = PROJECT_ROOT / "config" / "presets.yaml"
        if not presets_path.exists():
            return []
        with open(presets_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("presets", [])

    def build_plan(self, task_spec) -> PipelineExecutionPlan:
        """Build an execution plan from a task spec without running it.

        Useful for inspection, validation, or preview before execution.
        """
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        workspace = self._resource_service.ensure_workspace()
        output_dir = session.resolved_output_dir or str(workspace["output_dir"])

        source_lang, target_lang = self._resolve_profile_languages(
            task_spec.execution_profile
        )
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
                "mode": "custom-dir" if request.output_dir else "workspace-default",
                "custom_output_dir": request.output_dir or None,
            },
        )
        execution_profile = request.execution_profile or {
            "profile_version": "mainline.v1",
            "source_lang": request.source_lang,
            "target_lang": request.target_lang,
            "skip_existing": request.skip_existing,
            "output_mode": request.output_mode,
            "batch_root_dir": request.batch_root_dir,
            "stages": {
                "separate": request.use_vocal_separator,
                "asr": True,
                "translate": True,
                "tts": True,
                "mix": True,
                "export": True,
            },
            "profiles": {
                "separator": {
                    "category": "separator",
                    "provider": "builtin",
                    "model": request.vocal_model,
                    "common_options": {"mode": "vocals"},
                    "provider_options": {},
                },
                "asr": {
                    "category": "asr",
                    "provider": "faster_whisper",
                    "model": request.asr_model,
                    "common_options": {
                        "language": request.source_lang,
                        "output_format": "segments",
                        "timestamps": True,
                    },
                    "provider_options": {"disable_vad": True},
                },
                "translation": {
                    "category": "llm",
                    "provider": request.translate_provider,
                    "model": request.translate_model or "default",
                    "common_options": {
                        "source_lang": request.source_lang,
                        "target_lang": request.target_lang,
                        "preserve_timestamps": True,
                    },
                    "provider_options": {},
                },
                "tts": {
                    "category": "tts",
                    "provider": request.tts_engine,
                    "model": "default",
                    "common_options": {
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
                    "category": "mix",
                    "provider": "local",
                    "model": "default",
                    "common_options": {
                        "original_volume": request.original_volume,
                        "tts_volume_ratio": request.tts_volume_ratio,
                        "tts_delay": request.tts_delay,
                        "normalize": True,
                    },
                    "provider_options": {},
                },
                "export": {
                    "category": "export",
                    "provider": "local",
                    "model": "default",
                    "common_options": {
                        "subtitle_format": "srt",
                        "include_intermediate_files": True,
                    },
                    "provider_options": {},
                },
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

    @staticmethod
    def _resolve_profile_languages(execution_profile: dict[str, Any]) -> tuple[str, str]:
        if execution_profile.get("version") == 1:
            return (
                str(execution_profile.get("source_lang", "ja")),
                str(execution_profile.get("target_lang", "zh")),
            )
        if execution_profile.get("profile_version") == "mainline.v1":
            return (
                str(execution_profile.get("source_lang", "ja")),
                str(execution_profile.get("target_lang", "zh")),
            )
        pipeline_options = dict(execution_profile.get("pipeline", {}))
        return (
            str(pipeline_options.get("source_lang", "ja")),
            str(pipeline_options.get("target_lang", "zh")),
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
