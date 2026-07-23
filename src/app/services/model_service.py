"""Application-layer wrapper for core model services."""

from __future__ import annotations

import logging
import threading

from src.core.resources import get_model_service as get_core_model_service

from ..dto import (
    ModelOperationResult,
    ModelStatusIssueView,
    ModelStatusView,
    ModelSummary,
    ModelVerificationResult,
)
from ..errors import AppExecutionError, AppValidationError

logger = logging.getLogger(__name__)


class ModelService:
    """Stable application-facing facade for model operations."""

    def __init__(self, core_service=None, task_service=None):
        self.core_service = core_service or get_core_model_service()
        self._task_service = task_service

    def list_models(self, kind: str | None = None, category: str | None = None) -> list[ModelSummary]:
        entries = self.core_service.list_models(kind=kind, category=category)
        return [
            ModelSummary(
                model_id=entry.id,
                kind=entry.kind,
                category=entry.category,
                backend=entry.provider or entry.engine or "-",
                display_name=entry.display_name,
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
            },
        )
        task_id = task.task_id

        def _run():
            try:
                task_svc.start_task(task_id, "installing")
                self.core_service.install(
                    model_id,
                    mirror=mirror,
                    force=force,
                    install_mode=install_mode,
                    install_dependencies=install_dependencies,
                    install_recommended_assets=install_recommended_assets,
                    allow_fallback_variant=allow_fallback_variant,
                    on_progress=lambda frac, msg: task_svc.update_progress(task_id, frac, msg),
                )
                task_svc.complete_task(task_id, "installed")
            except Exception as exc:
                logger.error("async install failed for %s: %s", model_id, exc)
                task_svc.fail_task(task_id, str(exc))

        thread = threading.Thread(target=_run, name=f"install-{model_id}", daemon=True)
        thread.start()
        return task_id

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
