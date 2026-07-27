"""Application resource service for workspace and model directories."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

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
        module_checker: Callable[[str], bool] | None = None,
        ffmpeg_checker: Callable[[], tuple[bool, str]] | None = None,
        media_probe: Callable[[str], tuple[bool, str]] | None = None,
    ) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        self._manager = RuntimeWorkspaceManager(self.project_root)
        self._descriptor_service = descriptor_service or get_capability_descriptor_service()
        self._model_service = model_service or get_model_service()
        self._module_checker = module_checker or self._can_import
        self._ffmpeg_checker = ffmpeg_checker or self._check_ffmpeg_runtime
        self._media_probe = media_probe or self._probe_media

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
        input_path: str | None = None,
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
            issues.extend(self._check_pipeline_profile(profile, input_path=input_path))

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

    def _check_pipeline_profile(
        self,
        profile: dict,
        *,
        input_path: str | None = None,
    ) -> list[dict[str, object]]:
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

            requirements = dict(descriptor.get("runtime_requirements") or {})
            for module in requirements.get("python_modules") or []:
                if not self._module_checker(str(module)):
                    issues.append(
                        self._issue(
                            stage=stage_name,
                            category=category,
                            provider=provider,
                            model=requested_model,
                            code="PYTHON_DEPENDENCY_MISSING",
                            requirement=str(module),
                            message=f"Python dependency is unavailable: {module}",
                        )
                    )

            for tool in requirements.get("system_tools") or []:
                if shutil.which(str(tool)) is None:
                    issues.append(
                        self._issue(
                            stage=stage_name,
                            category=category,
                            provider=provider,
                            model=requested_model,
                            code="SYSTEM_TOOL_MISSING",
                            requirement=str(tool),
                            message=f"Required system tool is unavailable: {tool}",
                        )
                    )

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

        mix_stage = stages.get("mix")
        if isinstance(mix_stage, dict) and bool(mix_stage.get("enabled", True)):
            provider = str(mix_stage.get("provider") or "").strip()
            if provider != "ffmpeg":
                issues.append(
                    self._issue(
                        stage="mix",
                        category="media",
                        provider=provider,
                        model=None,
                        code="CAPABILITY_UNAVAILABLE",
                        requirement=f"media/{provider or '<empty>'}",
                        message=f"Unsupported mix provider: {provider or '<empty>'}",
                    )
                )
            else:
                available, detail = self._ffmpeg_checker()
                if not available:
                    issues.append(
                        self._issue(
                            stage="mix",
                            category="media",
                            provider=provider,
                            model=None,
                            code="SYSTEM_TOOL_MISSING",
                            requirement="ffmpeg",
                            message=detail or "FFmpeg runtime is unavailable",
                        )
                    )

        if input_path:
            issues.extend(self._check_input_path(input_path))
        return issues

    def _check_input_path(self, input_path: str) -> list[dict[str, object]]:
        source = Path(input_path)
        if not source.exists():
            return [
                self._input_issue(
                    input_path,
                    "INPUT_NOT_FOUND",
                    "Input file does not exist",
                )
            ]
        if not source.is_file():
            return [
                self._input_issue(
                    input_path,
                    "INPUT_NOT_FILE",
                    "Pipeline input must be a file",
                )
            ]
        try:
            if source.stat().st_size <= 0:
                return [
                    self._input_issue(
                        input_path,
                        "INPUT_EMPTY",
                        "Input media file is empty",
                    )
                ]
            with source.open("rb"):
                pass
        except OSError as exc:
            return [
                self._input_issue(
                    input_path,
                    "INPUT_NOT_READABLE",
                    f"Input file is not readable: {exc}",
                )
            ]

        available, detail = self._media_probe(str(source))
        if available:
            return []
        return [
            self._input_issue(
                input_path,
                "INPUT_MEDIA_INVALID",
                detail or "Input file is not decodable audio",
            )
        ]

    @classmethod
    def _input_issue(
        cls,
        input_path: str,
        code: str,
        message: str,
    ) -> dict[str, object]:
        return cls._issue(
            stage="prepare",
            category="input",
            provider="local",
            model=None,
            code=code,
            requirement=input_path,
            message=message,
            action="workbench",
        )

    @staticmethod
    def _can_import(module: str) -> bool:
        try:
            importlib.import_module(module)
            return True
        except Exception:
            return False

    @staticmethod
    def _ffmpeg_executable() -> str:
        from src.utils import get_ffmpeg

        return get_ffmpeg()

    @classmethod
    def _check_ffmpeg_runtime(cls) -> tuple[bool, str]:
        try:
            executable = cls._ffmpeg_executable()
            if not Path(executable).is_file():
                return False, f"FFmpeg executable does not exist: {executable}"
            result = subprocess.run(
                [executable, "-version"],
                check=False,
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, "FFmpeg executable could not be started"
            return True, ""
        except Exception as exc:
            return False, f"FFmpeg runtime is unavailable: {exc}"

    @classmethod
    def _probe_media(cls, input_path: str) -> tuple[bool, str]:
        try:
            import soundfile as sf

            info = sf.info(input_path)
            if info.duration > 0 and info.samplerate > 0 and info.channels > 0:
                return True, ""
        except Exception:
            pass

        try:
            executable = cls._ffmpeg_executable()
            result = subprocess.run(
                [
                    executable,
                    "-v",
                    "error",
                    "-t",
                    "0.1",
                    "-i",
                    input_path,
                    "-f",
                    "null",
                    "-",
                ],
                check=False,
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True, ""
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            return False, detail or "FFmpeg could not decode the input media"
        except Exception as exc:
            return False, f"Input media probe failed: {exc}"

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
