from __future__ import annotations

import importlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.config import config

from .model_catalog import ModelEntry


class ModelState:
    MISSING = "missing"
    INVALID = "invalid"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    UNCONFIGURED = "unconfigured"


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


class ModelStatusResolver:
    """Resolve installation and runtime readiness as separate facts."""

    _RUNTIME_IMPORTS = {
        "faster_whisper": ("faster_whisper",),
        "fun_asr": ("funasr",),
        "qwen3_asr": ("qwen_asr",),
        "qwen3": ("qwen_tts",),
        "voxcpm2": ("voxcpm",),
        "kokoro": ("kokoro", "soundfile"),
        "demucs": ("demucs",),
    }
    _EXTRA_IMPORTS = {
        "audio": ("torch",),
        "funasr": ("funasr",),
        "qwen_asr": ("qwen_asr",),
        "qwen3": ("qwen_tts",),
        "voxcpm2": ("voxcpm",),
        "kokoro": ("kokoro",),
    }

    def __init__(
        self,
        *,
        import_checker: Callable[[str], bool] | None = None,
        tool_checker: Callable[[str], bool] | None = None,
        gpu_checker: Callable[[], bool] | None = None,
    ) -> None:
        self._import_checker = import_checker or self._can_import
        self._tool_checker = tool_checker or self._has_system_tool
        self._gpu_checker = gpu_checker or self._has_cuda_gpu

    def resolve(self, entry: ModelEntry) -> ModelStatus:
        if entry.kind == "cloud":
            api_key = config.get(entry.api_key_config or "", "")
            if api_key:
                return ModelStatus(
                    entry.id,
                    ModelState.CONFIGURED,
                    "Credential configured",
                    executable=True,
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

        install_dir = entry.resolved_install_dir()
        if entry.install_strategy == "package":
            issues = self._runtime_issues(entry)
            package_issue = next(
                (issue for issue in issues if issue.code == "PYTHON_DEPENDENCY_MISSING"),
                None,
            )
            if package_issue is not None:
                return ModelStatus(
                    entry.id,
                    ModelState.MISSING,
                    package_issue.message,
                    install_dir,
                    executable=False,
                    issues=tuple(issues),
                )
            return self._installed_status(entry, install_dir, issues)

        if not install_dir.exists():
            issue = ModelStatusIssue(
                "MODEL_ASSET_MISSING",
                str(install_dir),
                "Model install directory is missing",
            )
            return ModelStatus(
                entry.id,
                ModelState.MISSING,
                issue.message,
                install_dir,
                issues=(issue,),
            )

        for required_dir in entry.required_dirs:
            if not (install_dir / required_dir).exists():
                issue = ModelStatusIssue(
                    "MODEL_ASSET_INVALID",
                    required_dir,
                    f"Required model directory is missing: {required_dir}",
                )
                return ModelStatus(
                    entry.id,
                    ModelState.INVALID,
                    issue.message,
                    install_dir,
                    issues=(issue,),
                )

        for required_file in entry.required_files:
            if not self._has_required_file(install_dir, required_file):
                issue = ModelStatusIssue(
                    "MODEL_ASSET_INVALID",
                    required_file,
                    f"Required model file is missing: {required_file}",
                )
                return ModelStatus(
                    entry.id,
                    ModelState.INVALID,
                    issue.message,
                    install_dir,
                    issues=(issue,),
                )

        return self._installed_status(
            entry,
            install_dir,
            self._runtime_issues(entry),
        )

    def _installed_status(
        self,
        entry: ModelEntry,
        install_dir: Path,
        issues: list[ModelStatusIssue],
    ) -> ModelStatus:
        if issues:
            return ModelStatus(
                entry.id,
                ModelState.INSTALLED,
                "Model is installed but runtime requirements are unavailable",
                install_dir,
                executable=False,
                issues=tuple(issues),
            )
        return ModelStatus(
            entry.id,
            ModelState.INSTALLED,
            "Model is installed and executable",
            install_dir,
            executable=True,
        )

    def _runtime_issues(self, entry: ModelEntry) -> list[ModelStatusIssue]:
        issues: list[ModelStatusIssue] = []
        modules: list[str] = []
        runtime_key = entry.provider or entry.engine or ""
        modules.extend(self._RUNTIME_IMPORTS.get(runtime_key, ()))
        for extra in entry.required_python_extras:
            modules.extend(self._EXTRA_IMPORTS.get(extra, ()))
        for requirement in entry.required_runtime_packages:
            module = self._package_import_name(requirement)
            if module:
                modules.append(module)

        for module in dict.fromkeys(modules):
            if not self._import_checker(module):
                issues.append(
                    ModelStatusIssue(
                        "PYTHON_DEPENDENCY_MISSING",
                        module,
                        f"Python dependency is unavailable: {module}",
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

        if entry.requires_gpu and not self._gpu_checker():
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
