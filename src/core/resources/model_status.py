from __future__ import annotations

import importlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import config
from src.core.runtime import RuntimeProfileResolver, get_runtime_profile_resolver

from .model_catalog import ModelEntry
from .provider_verification import (
    ProviderVerificationRegistry,
    get_provider_verification_registry,
)


class ModelState:
    MISSING = "missing"
    INVALID = "invalid"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelStatusIssue:
    code: str
    requirement: str
    message: str


@dataclass(frozen=True)
class ModelStatus:
    model_id: str
    status: str
    detail: str = ""
    path: Optional[Path] = None
    executable: bool = False
    issues: tuple[ModelStatusIssue, ...] = ()
    weights_ready: bool = False
    runtime_ready: bool = False
    shared_readonly: bool = False


class ModelStatusResolver:
    """Resolve installation and runtime readiness as separate facts."""

    _RUNTIME_IMPORTS = {
        "faster_whisper": ("faster_whisper", "ctranslate2"),
        "fun_asr": ("funasr", "torch", "torchaudio"),
        "qwen3_asr": ("qwen_asr",),
        "qwen3": ("qwen_tts",),
        "voxcpm2": ("voxcpm",),
        "demucs": ("demucs.pretrained", "demucs.apply", "julius", "soundfile", "numpy"),
    }
    _EXTRA_IMPORTS = {
        "audio": ("torch",),
        "funasr": ("funasr", "torch", "torchaudio"),
        "qwen_asr": ("qwen_asr",),
        "qwen3": ("qwen_tts",),
        "voxcpm2": ("voxcpm",),
    }

    def __init__(
        self,
        *,
        import_checker: Callable[[str], bool] | None = None,
        tool_checker: Callable[[str], bool] | None = None,
        gpu_checker: Callable[[], bool] | None = None,
        runtime_resolver: RuntimeProfileResolver | None = None,
        provider_verifications: ProviderVerificationRegistry | None = None,
    ) -> None:
        self._import_checker = import_checker or self._can_import
        self._cached_imports = import_checker is None
        self._tool_checker = tool_checker or self._has_system_tool
        self._gpu_checker = gpu_checker or self._has_cuda_gpu
        self._cached_gpu = gpu_checker is None
        self._runtime_resolver = runtime_resolver or get_runtime_profile_resolver()
        self._provider_verifications = (
            provider_verifications or get_provider_verification_registry()
        )

    def resolve(self, entry: ModelEntry) -> ModelStatus:
        if entry.kind == "cloud":
            api_key = str(config.get(entry.api_key_config or "", "") or "").strip()
            if api_key:
                provider = str(entry.provider or entry.engine or entry.id).strip()
                base_url = str(
                    config.get(f"api.{provider}_base_url", "") or ""
                ).strip()
                verification = self._provider_verifications.get_fresh(
                    provider,
                    api_key,
                    base_url,
                )
                if verification is not None and verification.success:
                    return ModelStatus(
                        entry.id,
                        ModelState.CONFIGURED,
                        verification.message
                        or "Provider connection and authentication are verified",
                        executable=True,
                    )
                if verification is not None:
                    issue = ModelStatusIssue(
                        "PROVIDER_VERIFICATION_FAILED",
                        provider,
                        verification.message
                        or "Provider connection or authentication verification failed",
                    )
                    return ModelStatus(
                        entry.id,
                        ModelState.CONFIGURED,
                        f"{issue.message}. Tasks may still be started; verify the connection manually or retry the task",
                        executable=True,
                        issues=(issue,),
                    )
                issue = ModelStatusIssue(
                    "PROVIDER_UNVERIFIED",
                    provider,
                    "Credential is configured. Connection verification is optional and can be started manually",
                )
                return ModelStatus(
                    entry.id,
                    ModelState.CONFIGURED,
                    issue.message,
                    executable=True,
                    issues=(issue,),
                )
            issue = ModelStatusIssue(
                "CREDENTIAL_MISSING",
                entry.api_key_config or "credential",
                "Required provider credential is not configured",
            )
            return ModelStatus(
                entry.id,
                ModelState.UNCONFIGURED,
                issue.message,
                executable=False,
                issues=(issue,),
            )

        from .model_assets import complete, shared
        path = entry.resolved_install_dir()
        weights_ready = complete(entry, path)
        issues = self._runtime_issues(entry)
        runtime_ready = not issues
        if not weights_ready:
            missing = next((name for name in entry.required_files if not (path / name).is_file() or not (path / name).stat().st_size), str(path))
            issues.append(ModelStatusIssue('MODEL_ASSET_INVALID' if path.exists() else 'MODEL_ASSET_MISSING', missing, f'权重缺失或不完整：{missing}；依赖检测不能确认模型可运行'))
        detail = ('权重文件完整' if weights_ready else '权重缺失或不完整') + '；' + ('依赖检查通过' if runtime_ready else '运行环境需处理') + '；尚未实际加载验证'
        return ModelStatus(entry.id, ModelState.INSTALLED if weights_ready else ModelState.INVALID if path.exists() else ModelState.MISSING,
                           detail, path, executable=weights_ready and runtime_ready, issues=tuple(issues),
                           weights_ready=weights_ready, runtime_ready=runtime_ready, shared_readonly=shared(entry, path))

    def _runtime_issues(self, entry: ModelEntry) -> list[ModelStatusIssue]:
        issues: list[ModelStatusIssue] = []
        modules: list[str] = []
        runtime = self._runtime_resolver.resolve(entry.runtime_profile)
        runtime_key = entry.provider or entry.engine or ""
        modules.extend(self._RUNTIME_IMPORTS.get(runtime_key, ()))
        for extra in entry.required_python_extras:
            modules.extend(self._EXTRA_IMPORTS.get(extra, ()))
        for requirement in entry.required_runtime_packages:
            module = self._package_import_name(requirement)
            if module:
                modules.append(module)

        runtime_missing = runtime.isolated and not runtime.python_executable.is_file()
        if runtime_missing:
            issues.append(
                ModelStatusIssue(
                    "RUNTIME_ENVIRONMENT_MISSING",
                    runtime.id,
                    f"Runtime environment is not installed: {runtime.id}",
                )
            )

        unique_modules = list(dict.fromkeys(modules))
        missing_modules: list[str] = []
        combined_import_failed = False
        if not runtime_missing and (runtime.isolated or self._cached_imports) and runtime.python_executable.is_file():
            if not self._runtime_resolver.check_modules(runtime.id, unique_modules):
                combined_import_failed = True
                missing_modules = [
                    module
                    for module in unique_modules
                    if not self._runtime_resolver.check_modules(runtime.id, [module])
                ]
        elif not runtime_missing:
            missing_modules = [
                module for module in unique_modules if not self._import_checker(module)
            ]

        for module in missing_modules:
            issues.append(
                ModelStatusIssue(
                    "PYTHON_DEPENDENCY_MISSING",
                    module,
                    f"Python dependency is unavailable: {module}",
                )
            )
        if combined_import_failed and not missing_modules:
            requirement = ",".join(unique_modules)
            issues.append(
                ModelStatusIssue(
                    "PYTHON_DEPENDENCY_INCOMPATIBLE",
                    requirement,
                    "Python dependencies import separately but fail when loaded together",
                )
            )

        for tool in entry.required_system_tools:
            if not self._tool_checker(tool):
                issues.append(
                    ModelStatusIssue(
                        "SYSTEM_TOOL_MISSING",
                        tool,
                        f"Required system tool is unavailable: {tool}",
                    )
                )

        if entry.requires_gpu and not runtime_missing:
            has_gpu = (
                self._runtime_resolver.has_ctranslate2_cuda(runtime.id)
                if runtime_key == "faster_whisper" else
                self._runtime_resolver.has_cuda(runtime.id)
                if (runtime.isolated or self._cached_gpu) and runtime.python_executable.is_file()
                else self._gpu_checker()
            )
            if not has_gpu:
                issues.append(
                    ModelStatusIssue(
                        "GPU_UNAVAILABLE",
                        entry.min_cuda or "CUDA GPU",
                        "A compatible CUDA GPU is required but unavailable",
                    )
                )
        return issues

    @staticmethod
    def _package_import_name(requirement: str) -> str:
        name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip()
        return name.replace("-", "_")

    @staticmethod
    def _can_import(module: str) -> bool:
        try:
            importlib.import_module(module)
            return True
        except Exception:
            return False

    @staticmethod
    def _has_system_tool(tool: str) -> bool:
        return shutil.which(tool) is not None

    @staticmethod
    def _has_cuda_gpu() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    @staticmethod
    def _has_required_file(install_dir: Path, required_file: str) -> bool:
        return (install_dir / required_file).is_file()
