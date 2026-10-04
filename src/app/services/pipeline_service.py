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
from src.core.subtitles.translation_reuse import prepare_translation_profile

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
                "suggestion": "请在引擎与资源的外部服务中检查配置并验证服务连接，确认无误后重试任务",
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
        from src.workspace_paths import directory_context
        session = self._session_service.get_session(task_spec.session_id)
        with directory_context(temp_root=session.resolved_temp_dir):
            return self._run_pipeline_task_spec(task_spec, progress_callback=progress_callback,
                cancel_event=cancel_event, manage_lifecycle=manage_lifecycle)

    def _run_pipeline_task_spec(self, task_spec, *, progress_callback=None,
                                cancel_event=None, manage_lifecycle=True):
        if task_spec.execution_profile.get("version") == 2:
            from .graph_pipeline_service import run_graph_task
            return run_graph_task(self, task_spec, progress_callback=progress_callback,
                                  cancel_event=cancel_event, manage_lifecycle=manage_lifecycle)
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
                companion_paths=[self._input_catalog_service.get_asset(a).absolute_path
                                 for a in session.companion_asset_ids],
            )
            workspace = self._resource_service.ensure_workspace()
            companion_paths = [self._input_catalog_service.get_asset(a).absolute_path
                               for a in session.companion_asset_ids]
            execution_profile = prepare_translation_profile(dict(task_spec.execution_profile),
                input_asset.absolute_path, companion_paths)
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

            companion_vtt_path = None if execution_profile.get("workflow") else self._resolve_companion_subtitle_path(session.companion_asset_ids, source_lang, input_asset.absolute_path)
            context = PipelineExecutionContext(
                task_id=task_spec.task_id,
                input_path=input_asset.absolute_path,
                output_dir=output_dir,
                source_lang=source_lang,
                target_lang=target_lang,
                companion_subtitle_path=companion_vtt_path,
                companion_subtitle_paths=companion_paths,
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
                if stage != "error":
                    current_stage = stage
                self._task_service.update_progress(
                    task_spec.task_id,
                    progress=progress,
                    message=message,
                    stage=current_stage,
                )

            plan = build_execution_plan(context)
            recovery_options = {}
            store = self._task_service.recovery_store
            manifest = store.manifest(task_spec.task_id) if store else None
            if manifest and isinstance(self._executor, PipelineExecutor):
                from src.core.orchestration.pipeline.recovery import PipelineRecovery
                from src.app.persistence.recovery_store import fingerprint
                recovery_options["recovery"] = PipelineRecovery(
                    store, task_spec.task_id, manifest.get("resume_of_task_id"), plan,
                    fingerprint(manifest["connections"]))
            results = self._executor.execute(
                plan,
                progress_callback=on_progress,
                stage_callback=on_stage,
                cancel_event=cancel_event,
                **recovery_options,
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
                task_error = getattr(exc, "task_error", None) or failure_error or _build_pipeline_task_error(
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
                    message=str(task_error.get("message") or task_error.get("detail") or str(exc)),
                    detail=str(task_error["detail"]),
                    stage=current_stage,
                    error=task_error,
                )
            if isinstance(
                exc,
                (AppValidationError, AppExecutionError, ResourceValidationError),
            ):
                raise
            error = AppExecutionError(str(exc))
            if getattr(exc, "task_error", None):
                error.task_error = dict(exc.task_error)
            raise error from exc

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
                stage=results.get("last_stage", "export"),
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
            companion_paths=request.companion_paths or ([request.vtt_path] if request.vtt_path else []),
        )
        task_spec = self.create_pipeline_task_spec(request, task_source=task_source)
        return self._task_service.get_task(task_spec.task_id), task_spec

    def _assert_task_ready(
        self,
        execution_profile: dict[str, Any],
        *,
        input_path: str | None = None,
        companion_paths: list[str] | None = None,
    ) -> None:
        """Apply the backend-authoritative readiness gate for V1 pipeline profiles."""
        if execution_profile.get("version") == 2:
            from .graph_pipeline_service import prepare_graph_profile
            try:
                execution_profile, _ = prepare_graph_profile(execution_profile,
                    declared_paths=[input_path, *(companion_paths or [])])
            except (ValueError, KeyError, OSError, TypeError) as exc:
                raise AppValidationError(str(exc)) from exc
        elif execution_profile.get("version") != 1:
            raise AppValidationError(
                "pipeline execution profile must use StageProfile version 1"
            )
        else:
            try:
                execution_profile = prepare_translation_profile(execution_profile, input_path, companion_paths)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc
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
        if task_spec.execution_profile.get("version") == 2:
            from src.core.orchestration.pipeline.graph_validation import build_graph_plan
            profile = task_spec.execution_profile
            return build_graph_plan(profile["graph"], profile["bindings"], task_id=task_spec.task_id,
                                    node_snapshots=profile.get("_graph_runtime", {}).get("node_snapshots", {}))
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        workspace = self._resource_service.ensure_workspace()
        companion_paths = [self._input_catalog_service.get_asset(a).absolute_path
                           for a in session.companion_asset_ids]
        execution_profile = prepare_translation_profile(dict(task_spec.execution_profile),
            input_asset.absolute_path, companion_paths)
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
        companion_vtt_path = None if execution_profile.get("workflow") else self._resolve_companion_subtitle_path(session.companion_asset_ids, source_lang, input_asset.absolute_path)

        context = PipelineExecutionContext(
            task_id=task_spec.task_id,
            input_path=input_asset.absolute_path,
            output_dir=output_dir,
            source_lang=source_lang,
            target_lang=target_lang,
            companion_subtitle_path=companion_vtt_path,
            companion_subtitle_paths=companion_paths,
            execution_profile=execution_profile,
        )
        return build_execution_plan(context)

    def create_pipeline_task_spec(
        self,
        request: PipelineRequest,
        *,
        task_source: str = "pipeline-service",
        _frozen_graph=None,
    ):
        workspace = self._workspace_service.resolve()
        inspected_assets = self._input_catalog_service.inspect_paths([request.input_path])
        primary_asset = inspected_assets[0]
        companion_paths = list(request.companion_paths)
        if request.vtt_path and request.vtt_path not in companion_paths:
            companion_paths.append(request.vtt_path)
        if (not companion_paths and not (request.execution_profile or {}).get("workflow")
                and (request.execution_profile or {}).get("version") != 2):
            companion_paths = [asset.absolute_path for asset in
                               self._input_catalog_service.discover_companions(primary_asset.asset_id)]
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
        execution_profile = (_frozen_graph.profile if _frozen_graph is not None
                             else self._resolve_execution_profile(request))
        from copy import deepcopy
        execution_profile = deepcopy(execution_profile)
        if execution_profile.get("version") == 2:
            from .graph_pipeline_service import (freeze_graph_speech, prepare_graph_profile,
                                                 validate_frozen_graph_submission)
            try:
                if _frozen_graph is None:
                    execution_profile, _ = prepare_graph_profile(execution_profile,
                        declared_paths=[primary_asset.absolute_path, *companion_paths])
                    execution_profile = freeze_graph_speech(execution_profile)
                else:
                    execution_profile = validate_frozen_graph_submission(_frozen_graph)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                raise AppValidationError(str(exc)) from exc
            execution_profile["_graph_runtime"]["connections_frozen"] = True
            task_spec, _ = self._task_service.create_task_spec(
                task_type="pipeline", task_source=task_source, session_id=session.session_id,
                input_asset_id=primary_asset.asset_id, companion_asset_ids=companion_asset_ids,
                execution_profile=execution_profile, graph_prepared=True,
                frozen_graph_connections=(None if _frozen_graph is None else _frozen_graph.connections))
            self._task_service.save_pipeline_manifest(task_spec.task_id,
                input_path=primary_asset.absolute_path, companion_paths=companion_paths,
                output_root=session.resolved_output_dir)
            return task_spec
        try:
            execution_profile = prepare_translation_profile(execution_profile,
                primary_asset.absolute_path, companion_paths)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        from src.task_connection_context import resolve_task_settings
        from src.config import config
        try:
            selected_settings = resolve_task_settings(config.to_dict(), execution_profile)
        except ValueError as exc:
            conditional = prepare_translation_profile(execution_profile, primary_asset.absolute_path,
                companion_paths, allow_unverified=True)
            if conditional.get("stages", {}).get("translate", {}).get("enabled", True):
                raise AppValidationError(str(exc)) from exc
            execution_profile = conditional
            selected_settings = config.to_dict()
        translate_stage = execution_profile.get("stages", {}).get("translate", {})
        if translate_stage.get("enabled", True) and translate_stage.get("options", {}).get("connection_ref"):
            if translate_stage.get("model") in (None, "", "default"):
                translate_stage["model"] = selected_settings["api"][f"{translate_stage['provider']}_model"]
        speech_stage = execution_profile.get("stages", {}).get("tts", {})
        if speech_stage and speech_stage.get("enabled", True):
            from .speech_service import get_speech_service
            try:
                snapshot = get_speech_service().pipeline_snapshot(speech_stage)
            except (ValueError, KeyError, FileNotFoundError) as exc:
                raise AppValidationError(str(exc)) from exc
            speech_stage["provider"] = snapshot["recipe"]["provider_id"]
            speech_stage["model"] = snapshot["recipe"]["model"]
            speech_stage["provider_options"] = {"speech_snapshot": snapshot}
        task_spec, _ = self._task_service.create_task_spec(
            task_type="pipeline",
            task_source=task_source,
            session_id=session.session_id,
            input_asset_id=primary_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            execution_profile=execution_profile,
        )
        self._task_service.save_pipeline_manifest(
            task_spec.task_id, input_path=primary_asset.absolute_path,
            companion_paths=[self._input_catalog_service.get_asset(asset_id).absolute_path
                             for asset_id in companion_asset_ids],
            output_root=session.resolved_output_dir,
        )
        return task_spec

    def create_frozen_graph_task(self, submission, *, output_dir: str, task_source: str):
        """Admit one already prepared batch group through the ordinary task lifecycle."""
        from .graph_pipeline_service import validate_frozen_graph_submission
        try:
            validate_frozen_graph_submission(submission)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise AppValidationError(str(exc)) from exc
        paths = submission.paths
        spec = self.create_pipeline_task_spec(
            PipelineRequest(input_path=paths[0], companion_paths=paths[1:],
                            output_dir=output_dir, execution_profile=submission.profile),
            task_source=task_source, _frozen_graph=submission)
        return self._task_service.get_task(spec.task_id), spec

    def validate_frozen_graph_resources(self, submission) -> None:
        """Validate only the common selected capabilities before accepting a batch."""
        from contextlib import nullcontext
        from src.task_connection_context import connection_context
        issues = self._resource_service._check_graph_profile(submission.profile,
            node_context=lambda node: connection_context(submission.connections[node["id"]])
            if node["kind"] == "translate" else nullcontext())
        if issues:
            raise AppValidationError("; ".join(f"{issue['stage']}: {issue['message']}" for issue in issues))

    def resume_pipeline_task(self, task_id: str):
        if self._task_service.get_task_spec(task_id).execution_profile.get("version") == 2:
            raise AppValidationError("图任务暂不支持阶段续跑；显式重试会重新执行全部节点")
        if (self._task_service.get_task(task_id).error or {}).get("result_unknown"):
            raise AppValidationError("远端请求结果未知，请核对服务端结果和计费后创建新任务")
        stage = self._task_service.get_task_spec(task_id).execution_profile.get("stages", {}).get("tts", {})
        snapshot = stage.get("provider_options", {}).get("speech_snapshot")
        if stage.get("enabled"):
            if not snapshot:
                raise AppValidationError("旧配音任务仅保留历史，请选择新配方创建任务")
            from .speech_service import get_speech_service
            from src.core.speech.compiler import COMPILER_VERSION
            if snapshot["compiler_version"] != COMPILER_VERSION:
                raise AppValidationError("原配音编译器版本已改变，请创建新任务")
            get_speech_service().connection_context(snapshot["connection"])
        info = self._task_service.recovery_info(task_id)
        if not info["can_resume"]:
            raise AppValidationError(info["reason"])
        manifest = self._task_service.recovery_store.manifest(task_id)
        workspace = self._workspace_service.resolve()
        primary = self._input_catalog_service.inspect_paths([manifest["input_path"]])[0]
        companions = self._input_catalog_service.inspect_paths(manifest["companion_paths"])
        companion_ids = [asset.asset_id for asset in companions]
        session = self._session_service.create_session(
            workspace_id=workspace.workspace_id, mode="single-audio",
            input_asset_ids=[primary.asset_id], primary_input_asset_id=primary.asset_id,
            companion_asset_ids=companion_ids,
            output_policy={"mode": "task-scoped-root", "custom_output_dir": manifest["output_root"]})
        return self._task_service.resume_pipeline_task(
            task_id, session_id=session.session_id, input_asset_id=primary.asset_id,
            companion_asset_ids=companion_ids)

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
            if profile.get("version") == 2:
                from src.core.orchestration.pipeline.graph_validation import validate_graph_profile
                try:
                    return validate_graph_profile(profile)
                except ValueError as exc:
                    raise AppValidationError(str(exc)) from exc
            if profile.get("version") != 1 or not isinstance(
                profile.get("stages"), dict
            ):
                raise AppValidationError(
                    "pipeline execution profile must use StageProfile version 1"
                )
            return profile

        if request.voice_profile_id:
            raise AppValidationError("旧音色档案不能直接用于新任务，请导入并选择 Speech 生成规则")
        from .tts_engine_service import get_tts_engine_service
        options = {} if request.speech_recipe_id else {"language": request.target_lang}
        if request.tts_voice:
            options["voice"] = request.tts_voice
        if request.tts_speed != 1:
            options["speed"] = request.tts_speed
        try:
            tts_stage = get_tts_engine_service().build_stage(provider=request.tts_engine or None,
                model=request.tts_model or None, common_options=options,
                provider_options=request.engine_params.get(request.tts_engine, {}),
                connection_ref=request.tts_connection_ref, recipe_id=request.speech_recipe_id)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise AppValidationError(str(exc)) from exc
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
                "tts": {"enabled": True, **tts_stage},
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

    def _resolve_companion_subtitle_path(self, companion_asset_ids: list[str], source_lang: str = "auto", input_path: str | None = None) -> str | None:
        from src.core.subtitles.companions import inspect_subtitle, is_source_subtitle
        if input_path:
            from src.core.subtitles.translation_reuse import audio_duration, usable_subtitles
            paths = [self._input_catalog_service.get_asset(a).absolute_path for a in companion_asset_ids]
            valid = usable_subtitles(paths, source_lang, audio_duration(input_path))
            if valid:
                return valid[0]["path"]
        fallback = None
        for asset_id in companion_asset_ids:
            asset = self._input_catalog_service.get_asset(asset_id)
            if asset.kind == "subtitle" or Path(asset.absolute_path).suffix.lower() == ".txt":
                fallback = fallback or asset.absolute_path
                if asset.kind == "subtitle" and is_source_subtitle(inspect_subtitle(asset.absolute_path), source_lang):
                    return asset.absolute_path
        return fallback

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
        if results.get("workflow_outputs") is not None:
            for artifact in results["workflow_outputs"]:
                path = artifact["path"]
                self._artifact_service.register_artifact(task_id=task_id, path=path,
                    artifact_type=artifact["type"], label=artifact["label"], preview_kind=artifact["preview"],
                    stage=artifact["stage"], is_primary=path == results.get("primary_output"),
                    metadata={**artifact.get("metadata", {}), **({"node_id": artifact["node_id"],
                        "port": artifact["port"]} if "node_id" in artifact else {})})
            return
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
                is_primary=not bool(mix_path) and not results.get("direct_subtitle_tts", False),
            )
        for file_key, stage_name, artifact_type, preview_kind in (
            ("vocal_path", "separation", "audio.vocals", "audio"),
            ("tts_audio_path", "tts", "audio.tts", "audio"),
            ("transcript_path", "asr", "text.transcript", "text"),
            ("alignment_path", "align", "alignment.timestamps", "json"),
            ("aligned_subtitle_path", "align", "subtitle.aligned", "subtitle"),
            ("alignment_original_path", "align", "alignment.original", "json"),
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
                    is_primary=file_key == "tts_audio_path" and results.get("direct_subtitle_tts", False),
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
