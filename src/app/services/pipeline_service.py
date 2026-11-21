"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.core.orchestration import PipelineExecutor
from src.core.orchestration.pipeline.graph_models import GraphExecutionPlan
from src.utils import sanitize_filename
from src.core.speech.store import reference_submission_operation

from ..dto import PipelineRequest, PipelineResult
from ..errors import AppValidationError, ResourceValidationError
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
        from .graph_pipeline_service import run_graph_task
        if task_spec.execution_profile.get("version") != 2:
            raise AppValidationError("V1 任务已归档，请按 V2 节点图重新提交")
        return run_graph_task(self, task_spec, progress_callback=progress_callback,
                              cancel_event=cancel_event, manage_lifecycle=manage_lifecycle)

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
        from .graph_pipeline_service import prepare_graph_profile
        try:
            execution_profile, _ = prepare_graph_profile(execution_profile,
                declared_paths=[input_path, *(companion_paths or [])])
        except (ValueError, KeyError, OSError, TypeError) as exc:
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

    def build_plan(self, task_spec) -> GraphExecutionPlan:
        """Build an execution plan from a task spec without running it.

        Useful for inspection, validation, or preview before execution.
        """
        from src.core.orchestration.pipeline.graph_validation import build_graph_plan
        profile = task_spec.execution_profile
        if profile.get("version") != 2:
            raise AppValidationError("V1 任务已归档，请按 V2 节点图重新提交")
        session = self._session_service.get_session(task_spec.session_id)
        primary = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        output_dir = self._resolve_task_output_dir(task_id=task_spec.task_id, input_path=primary.absolute_path,
            execution_profile=profile, session_output_root=session.resolved_output_dir,
            workspace_output_root=self._workspace_service.resolve().default_output_root)
        return build_graph_plan(profile["graph"], profile["bindings"], task_id=task_spec.task_id, output_dir=output_dir,
                                node_snapshots=profile.get("_graph_runtime", {}).get("node_snapshots", {}))

    @reference_submission_operation
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
                "custom_output_dir": (request.batch_root_dir if request.output_mode == "batch" else None) or request.output_dir or None,
            },
        )
        execution_profile = (_frozen_graph.profile if _frozen_graph is not None
                             else self._resolve_execution_profile(request))
        from copy import deepcopy
        execution_profile = deepcopy(execution_profile)
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
        info = self._task_service.recovery_info(task_id)
        if not info["can_resume"]:
            raise AppValidationError(info["reason"])
        manifest = self._task_service.recovery_store.manifest(task_id)
        workspace = self._workspace_service.resolve()
        primary = self._input_catalog_service.inspect_paths([manifest["input_path"]])[0]
        companion_ids = [asset.asset_id for asset in self._input_catalog_service.inspect_paths(manifest["companion_paths"])]
        session = self._session_service.create_session(
            workspace_id=workspace.workspace_id, mode="single-audio", input_asset_ids=[primary.asset_id],
            primary_input_asset_id=primary.asset_id, companion_asset_ids=companion_ids,
            output_policy={"mode": "task-scoped-root", "custom_output_dir": manifest["output_root"]})
        return self._task_service.resume_pipeline_task(task_id, session_id=session.session_id,
            input_asset_id=primary.asset_id, companion_asset_ids=companion_ids)

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
            from src.core.orchestration.pipeline.graph_validation import validate_graph_profile
            from src.core.orchestration.pipeline.graph_legacy import legacy_profile_to_graph
            profile = dict(request.execution_profile)
            try:
                if profile.get("version") == 1:
                    profile = {"version": 2, **legacy_profile_to_graph(profile)}
                return validate_graph_profile(profile)
            except ValueError as exc:
                raise AppValidationError(str(exc)) from exc

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
        from .graph_pipeline_service import default_dubbing_profile
        try:
            return default_dubbing_profile(request, tts_stage)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc

    def _register_pipeline_artifacts(
        self,
        *,
        task_id: str,
        results: dict[str, Any],
    ) -> None:
        for artifact in results["workflow_outputs"]:
            self._artifact_service.register_artifact(
                task_id=task_id, path=artifact["path"], artifact_type=artifact["type"],
                label=artifact["label"], preview_kind=artifact["preview"], stage=artifact["stage"],
                is_primary=artifact["path"] == results.get("primary_output"),
                metadata={**artifact.get("metadata", {}), "node_id": artifact["node_id"], "port": artifact["port"]},
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
