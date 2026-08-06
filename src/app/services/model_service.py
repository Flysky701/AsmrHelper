"""Application-layer wrapper for core model services."""

from __future__ import annotations

import logging
import threading

from src.core.resources import get_model_service as get_core_model_service
from src.core.tasks import TaskDispatcher

from ..dto import (
    ModelOperationResult,
    ModelStatusIssueView,
    ModelStatusView,
    ModelSummary,
    ModelVerificationResult,
)
from ..errors import AppExecutionError, AppValidationError
from .task_service import TaskService, get_task_dispatcher

logger = logging.getLogger(__name__)


class ModelService:
    """Stable application-facing facade for model operations."""

    def __init__(self, core_service=None, task_service=None, dispatcher=None):
        self.core_service = core_service or get_core_model_service()
        self._task_service = task_service
        self._dispatcher = dispatcher
        if self._dispatcher is None and task_service is None:
            self._dispatcher = get_task_dispatcher()
        elif self._dispatcher is None and isinstance(task_service, TaskService):
            self._dispatcher = TaskDispatcher(
                task_service.registry,
                task_service=task_service,
            )
        if self._dispatcher is not None:
            self._dispatcher.register_executor(
                "model_install",
                self._execute_model_install,
            )

    def list_models(self, kind: str | None = None, category: str | None = None) -> list[ModelSummary]:
        entries = self.core_service.list_models(kind=kind, category=category)
        return [
            ModelSummary(
                model_id=entry.id,
                kind=entry.kind,
                category=entry.category,
                backend=entry.provider or entry.engine or "-",
                display_name=entry.display_name,
                install_strategy=entry.install_strategy or "",
                capability_models=entry.capability_models or [entry.id],
                supports_install=entry.supports_install,
                supports_remove=entry.supports_remove,
                family_id=entry.family_id,
                variant_group=entry.variant_group,
                variant_tier=entry.variant_tier,
                is_primary_variant=entry.is_primary_variant,
                dependency_group=entry.dependency_group,
                runtime_profile=entry.runtime_profile,
                preferred_runtime=entry.preferred_runtime,
                install_modes=entry.install_modes,
                default_install_mode=entry.default_install_mode,
                required_assets=entry.required_assets,
                recommended_assets=entry.recommended_assets,
                required_system_tools=entry.required_system_tools,
                supported_os=entry.supported_os,
            )
            for entry in entries
        ]

    def get_model_status(self, model_id: str) -> ModelStatusView:
        status = self._get_core_status(model_id)
        return ModelStatusView(
            model_id=status.model_id,
            status=status.status,
            detail=status.detail,
            executable=status.executable,
            issues=[
                ModelStatusIssueView(
                    code=issue.code,
                    requirement=issue.requirement,
                    message=issue.message,
                )
                for issue in status.issues
            ],
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
                executable=status.executable,
                issues=[
                    ModelStatusIssueView(
                        code=issue.code,
                        requirement=issue.requirement,
                        message=issue.message,
                    )
                    for issue in status.issues
                ],
            )
            for status in statuses
        ]

    def install_model(
        self,
        model_id: str,
        mirror: str | None = None,
        force: bool = False,
        install_mode: str = "single",
        install_dependencies: bool = True,
        install_recommended_assets: bool = False,
        allow_fallback_variant: bool = False,
    ) -> ModelOperationResult:
        return self._run_model_operation(
            action="install",
            model_id=model_id,
            runner=lambda: self.core_service.install(
                model_id,
                mirror=mirror,
                force=force,
                install_mode=install_mode,
                install_dependencies=install_dependencies,
                install_recommended_assets=install_recommended_assets,
                allow_fallback_variant=allow_fallback_variant,
            ),
        )

    def install_model_async(
        self,
        model_id: str,
        mirror: str | None = None,
        force: bool = False,
        install_mode: str = "single",
        install_dependencies: bool = True,
        install_recommended_assets: bool = False,
        allow_fallback_variant: bool = False,
    ) -> str:
        """Start async model installation, returns task_id for SSE subscription."""
        self._get_model_entry(model_id)
        task_svc = self._get_task_service()
        _spec, task = task_svc.create_task_spec(
            task_type="model_install",
            task_source="api",
            session_id="",
            execution_profile={
                "operation": "install",
                "model_id": model_id,
                "mirror": mirror,
                "force": force,
                "install_mode": install_mode,
                "install_dependencies": install_dependencies,
                "install_recommended_assets": install_recommended_assets,
                "allow_fallback_variant": allow_fallback_variant,
            },
        )
        task_id = task.task_id

        if self._dispatcher is None:
            raise AppExecutionError("model installer dispatcher is not configured")
        self._dispatcher.submit(task_id)
        return task_id

    def _execute_model_install(self, task_spec, context):
        profile = dict(task_spec.execution_profile)
        model_id = str(profile.get("model_id") or "")
        if context.cancellation_requested:
            raise AppExecutionError("cancelled by user")

        def _on_progress(frac, message):
            if context.cancellation_requested:
                raise AppExecutionError("cancelled by user")
            context.update_progress(
                float(frac),
                str(message),
                stage="install",
            )

        context.update_progress(
            0.0,
            message="waiting for model installer",
            stage="install",
        )
        self._get_model_entry(model_id)
        installed = self.core_service.install(
            model_id,
            mirror=profile.get("mirror"),
            force=bool(profile.get("force", False)),
            install_mode=profile.get("install_mode", "single"),
            install_dependencies=bool(profile.get("install_dependencies", True)),
            install_recommended_assets=bool(profile.get("install_recommended_assets", False)),
            allow_fallback_variant=bool(profile.get("allow_fallback_variant", False)),
            on_progress=_on_progress,
        )
        if not installed:
            raise AppExecutionError(
                f"model installation failed or runtime dependencies conflict: {model_id}"
            )
        return {"detail": f"installed {model_id}"}

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

    def unload_model(self, model_id: str) -> ModelOperationResult:
        """Unload a runtime model instance, releasing GPU memory."""
        entry = self._get_model_entry(model_id)
        category = getattr(entry, "category", None)
        if not category:
            raise AppValidationError(f"model '{model_id}' has no category, cannot unload")

        provider = getattr(entry, "provider", None) or getattr(entry, "engine", None)
        if not provider:
            raise AppValidationError(f"model '{model_id}' has no provider, cannot unload")

        try:
            registry = self._get_registry(category)
            registry.unload(provider)
            self._try_clear_gpu()
        except Exception as exc:
            raise AppExecutionError(f"failed to unload model '{model_id}': {exc}") from exc

        logger.info("unloaded model %s (category=%s)", model_id, category)
        status = self.get_model_status(model_id)
        return ModelOperationResult(
            action="unload",
            model_id=model_id,
            success=True,
            status=status.status,
            detail=status.detail,
        )

    def unload_all_models(self) -> None:
        """Unload all runtime model instances, releasing GPU memory."""
        try:
            for registry in self._all_registries():
                registry.unload_all()
            self._try_clear_gpu()
        except Exception as exc:
            raise AppExecutionError(f"failed to unload all models: {exc}") from exc
        logger.info("unloaded all models")

    def _get_model_entry(self, model_id: str):
        try:
            return self.core_service.get_model(model_id)
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

    def _get_task_service(self):
        if self._task_service is not None:
            return self._task_service
        from .task_service import get_task_service
        return get_task_service()

    @staticmethod
    def _get_registry(category: str):
        """Get the engine registry for a given category."""
        from src.core.engines.tts import get_tts_registry
        from src.core.engines.asr import get_asr_registry
        from src.core.engines.llm import get_llm_registry
        from src.core.engines.separator import get_separator_registry

        registries = {
            "tts": get_tts_registry,
            "asr": get_asr_registry,
            "llm": get_llm_registry,
            "separator": get_separator_registry,
        }
        getter = registries.get(category)
        if not getter:
            raise AppValidationError(f"unknown model category: {category}")
        return getter()

    @staticmethod
    def _all_registries():
        """Return all engine registry instances."""
        from src.core.engines.tts import get_tts_registry
        from src.core.engines.asr import get_asr_registry
        from src.core.engines.llm import get_llm_registry
        from src.core.engines.separator import get_separator_registry

        return [get_tts_registry(), get_asr_registry(), get_llm_registry(), get_separator_registry()]

    @staticmethod
    def _try_clear_gpu():
        """Attempt to clear GPU cache after unload."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

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
