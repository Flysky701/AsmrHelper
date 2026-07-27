"""Application resource service for workspace and model directories."""

from __future__ import annotations

import threading
from pathlib import Path

from src.core.runtime import ResourceStatus, RuntimeWorkspaceManager
from .capability_descriptor_service import (
    CapabilityDescriptorService,
    get_capability_descriptor_service,
)
from .model_service import ModelService, get_model_service


class ResourceService:
    """Resolve and prepare app-level workspace resources."""

    _STAGE_CATEGORIES = {
        "separate": "separator",
        "asr": "asr",
        "translate": "llm",
        "tts": "tts",
    }

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        descriptor_service: CapabilityDescriptorService | None = None,
        model_service: ModelService | None = None,
    ) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        self._manager = RuntimeWorkspaceManager(self.project_root)
        self._descriptor_service = descriptor_service or get_capability_descriptor_service()
        self._model_service = model_service or get_model_service()

    def ensure_workspace(self) -> dict[str, Path]:
        workspace = self._manager.ensure_workspace()
        return {
            "project_root": Path(workspace.project_root),
            "output_dir": Path(workspace.output_dir),
            "models_dir": Path(workspace.models_dir),
        }

    def get_runtime_resources(self) -> dict[str, str]:
        workspace = self._manager.ensure_workspace()
        return {
            "project_root": workspace.project_root,
            "output_dir": workspace.output_dir,
            "models_dir": workspace.models_dir,
        }

    def check_required_resources(self) -> list[ResourceStatus]:
        return self._manager.check_required_resources()

    def get_runtime_capabilities(self) -> dict[str, object]:
        resources = self.get_runtime_resources()
        statuses = self.check_required_resources()
        return {
            "resources": resources,
            "checks": [
                {
                    "name": status.name,
                    "available": status.available,
                    "detail": status.detail,
                    "metadata": dict(status.metadata),
                }
                for status in statuses
            ],
        }

    def check_task_readiness(
        self,
        *,
        task_type: str,
        execution_profile: dict | None = None,
    ) -> dict[str, object]:
        profile = dict(execution_profile or {})
        issues: list[dict[str, object]] = []

        for status in self.check_required_resources():
            if not status.available:
                issues.append(
                    self._issue(
                        stage="prepare",
                        category="runtime",
                        provider="workspace",
                        model=None,
                        code="RESOURCE_MISSING",
                        requirement=status.name,
                        message=status.detail or f"Required resource is unavailable: {status.name}",
                    )
                )

        if task_type == "pipeline":
            issues.extend(self._check_pipeline_profile(profile))

        missing = list(
            dict.fromkeys(str(issue["requirement"]) for issue in issues)
        )
        return {
            "task_type": task_type,
            "ready": not issues,
            "missing_requirements": missing,
            "issues": issues,
            "execution_profile": profile,
        }

    def _check_pipeline_profile(self, profile: dict) -> list[dict[str, object]]:
        stages = profile.get("stages")
        if not isinstance(stages, dict):
            return [
                self._issue(
                    stage="profile",
                    category="pipeline",
                    provider="",
                    model=None,
                    code="INVALID_EXECUTION_PROFILE",
                    requirement="execution_profile.stages",
                    message="Pipeline execution profile must contain a stages object",
                )
            ]

        issues: list[dict[str, object]] = []
        models = self._model_service.list_models()
        for stage_name, category in self._STAGE_CATEGORIES.items():
            stage = stages.get(stage_name)
            if not isinstance(stage, dict) or not bool(stage.get("enabled", True)):
                continue

            provider = str(stage.get("provider") or "").strip()
            requested_model = str(stage.get("model") or "").strip() or None
            try:
                descriptor = self._descriptor_service.get_descriptor(category, provider)
            except Exception:
                issues.append(
                    self._issue(
                        stage=stage_name,
                        category=category,
                        provider=provider,
                        model=requested_model,
                        code="CAPABILITY_UNAVAILABLE",
                        requirement=f"{category}/{provider or '<empty>'}",
                        message=f"Unsupported {category} provider: {provider or '<empty>'}",
                    )
                )
                continue

            resolved_model = requested_model
            if not resolved_model or resolved_model == "default":
                resolved_model = descriptor.get("default_model")
            supported = list(descriptor.get("supported_models") or [])
            if resolved_model and supported and resolved_model not in supported:
                issues.append(
                    self._issue(
                        stage=stage_name,
                        category=category,
                        provider=provider,
                        model=resolved_model,
                        code="MODEL_UNSUPPORTED",
                        requirement=resolved_model,
                        message=f"Model {resolved_model} is not supported by {category}/{provider}",
                    )
                )
                continue

            candidates = [
                model
                for model in models
                if model.category == category and model.backend == provider
            ]
            exact = next(
                (model for model in candidates if model.model_id == resolved_model),
                None,
            )
            selected = exact or (candidates[0] if len(candidates) == 1 else None)
            if selected is None:
                continue

            status = self._model_service.get_model_status(selected.model_id)
            if status.executable:
                continue
            for model_issue in status.issues or []:
                issues.append(
                    self._issue(
                        stage=stage_name,
                        category=category,
                        provider=provider,
                        model=selected.model_id,
                        code=model_issue.code,
                        requirement=model_issue.requirement,
                        message=model_issue.message,
                        action="settings"
                        if model_issue.code == "CREDENTIAL_MISSING"
                        else "engines",
                    )
                )
            if not status.issues:
                issues.append(
                    self._issue(
                        stage=stage_name,
                        category=category,
                        provider=provider,
                        model=selected.model_id,
                        code="MODEL_NOT_EXECUTABLE",
                        requirement=selected.model_id,
                        message=status.detail or f"Model is not executable: {selected.model_id}",
                    )
                )
        return issues

    @staticmethod
    def _issue(
        *,
        stage: str,
        category: str,
        provider: str,
        model: str | None,
        code: str,
        requirement: str,
        message: str,
        action: str = "engines",
    ) -> dict[str, object]:
        return {
            "stage": stage,
            "category": category,
            "provider": provider,
            "model": model,
            "code": code,
            "requirement": requirement,
            "message": message,
            "action": action,
        }


_service: ResourceService | None = None
_lock = threading.Lock()


def get_resource_service() -> ResourceService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ResourceService()
    return _service
