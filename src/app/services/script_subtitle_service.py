"""Application-layer wrapper for script-to-subtitle workflows."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..dto.script_subtitle import ScriptSubtitleRequest, ScriptSubtitleResult
from ..errors import AppExecutionError, AppValidationError

_SUPPORTED_OUTPUT_FORMATS = frozenset({"vtt", "srt", "lrc"})
_SUPPORTED_VERTICAL_MODES = frozenset({"auto", "horizontal", "vertical"})

ScriptToSubtitlePipeline = None


def _load_pipeline_runtime():
    global ScriptToSubtitlePipeline
    if ScriptToSubtitlePipeline is None:
        from src.core.subtitles.script_to_subtitle import (
            ScriptToSubtitlePipeline as core_pipeline,
        )

        ScriptToSubtitlePipeline = core_pipeline
    return ScriptToSubtitlePipeline


class ScriptSubtitleService:
    """Stable facade over the core ScriptToSubtitlePipeline."""

    def __init__(self, *, task_service=None, dispatcher=None, artifact_service=None) -> None:
        self._task_service = task_service
        self._dispatcher = dispatcher
        self._artifact_service = artifact_service
        if self._dispatcher is not None:
            self._dispatcher.register_executor(
                "subtitle.script_to_vtt",
                self._execute_task,
            )

    def create_task(self, request: ScriptSubtitleRequest):
        request = self._with_default_output(request)
        self._validate_task_request(request)
        task_service, dispatcher, _ = self._task_dependencies()
        profile = {
            "script_path": request.script_path,
            "output_path": request.output_path,
            "audio_path": request.audio_path,
            "vtt_path": request.vtt_path,
            "fmt": request.fmt,
            "use_llm_clean": request.use_llm_clean,
            "asr_model_size": request.asr_model_size,
            "asr_language": request.asr_language,
            "track_index": request.track_index,
            "vertical_mode": request.vertical_mode,
            "debug_dir": request.debug_dir,
        }
        companion_paths = [path for path in (request.audio_path, request.vtt_path) if path]
        spec, _ = task_service.create_task_spec(
            task_type="subtitle.script_to_vtt",
            task_source="subtitle-workshop",
            session_id="",
            input_asset_id=request.script_path,
            companion_asset_ids=companion_paths,
            execution_profile=profile,
        )
        return dispatcher.submit(spec.task_id)

    def _execute_task(self, task_spec, context) -> dict[str, Any]:
        profile = dict(task_spec.execution_profile)
        request = ScriptSubtitleRequest(
            script_path=str(profile.get("script_path") or task_spec.input_asset_id),
            output_path=str(profile.get("output_path") or ""),
            audio_path=profile.get("audio_path") or None,
            vtt_path=profile.get("vtt_path") or None,
            fmt=str(profile.get("fmt") or "vtt"),
            use_llm_clean=bool(profile.get("use_llm_clean", True)),
            asr_model_size=str(profile.get("asr_model_size") or "large-v3"),
            asr_language=str(profile.get("asr_language") or "ja"),
            track_index=profile.get("track_index"),
            vertical_mode=str(profile.get("vertical_mode") or "auto"),
            debug_dir=profile.get("debug_dir") or None,
        )

        def progress(stage: str, percent: int, message: str) -> None:
            if context.cancellation_requested:
                raise RuntimeError("cancelled by user")
            ranges = {
                "clean_script": (0.0, 0.2),
                "asr_recognize": (0.2, 0.65),
                "llm_align": (0.65, 0.95),
            }
            start, end = ranges.get(stage, (0.0, 0.95))
            normalized = start + (end - start) * max(0, min(percent, 100)) / 100
            context.update_progress(normalized, message=message, stage=stage)

        if request.vtt_path:
            result = self.run_from_existing_vtt(request, progress_callback=progress)
        elif request.audio_path:
            result = self.run_full(request, progress_callback=progress)
        else:
            result = self.run_text_only(request, progress_callback=progress)

        if context.cancellation_requested:
            raise RuntimeError("cancelled by user")
        if not result.output_path:
            raise AppExecutionError("script subtitle task produced no output")

        _, _, artifact_service = self._task_dependencies()
        artifact_service.register_artifact(
            task_id=task_spec.task_id,
            artifact_type="subtitle.txt" if result.mode == "text_only" else f"subtitle.{request.fmt}",
            path=result.output_path,
            label="Cleaned Script" if result.mode == "text_only" else "Script Subtitle Output",
            preview_kind="subtitle",
            stage="script_to_subtitle",
            is_primary=True,
            metadata={"mode": result.mode, "line_count": result.line_count},
        )
        context.update_progress(1.0, message="台本转字幕完成", stage="script_to_subtitle")
        return {
            "primary_output": result.output_path,
            "artifact_set_id": task_spec.task_id,
            "mode": result.mode,
            "line_count": result.line_count,
        }

    def run_full(
        self,
        request: ScriptSubtitleRequest,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> ScriptSubtitleResult:
        self._validate_common(request)
        if not request.audio_path:
            raise AppValidationError("audio_path is required")

        audio_path = Path(request.audio_path)
        if not audio_path.exists():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")

        self._ensure_output_parent(request.output_path)
        pipeline = self._build_pipeline()

        try:
            output_path = pipeline.run(
                script_path=request.script_path,
                audio_path=str(audio_path),
                output_path=request.output_path,
                fmt=request.fmt,
                use_llm_clean=request.use_llm_clean,
                asr_model_size=request.asr_model_size,
                asr_language=request.asr_language,
                track_index=request.track_index,
                vertical_mode=request.vertical_mode,
                progress_callback=progress_callback,
                debug_dir=request.debug_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return ScriptSubtitleResult(mode="full", output_path=str(output_path))

    def run_from_existing_vtt(
        self,
        request: ScriptSubtitleRequest,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> ScriptSubtitleResult:
        self._validate_common(request)
        if not request.vtt_path:
            raise AppValidationError("vtt_path is required")

        vtt_path = Path(request.vtt_path)
        if not vtt_path.exists():
            raise AppValidationError(f"vtt file does not exist: {request.vtt_path}")

        self._ensure_output_parent(request.output_path)
        pipeline = self._build_pipeline()

        try:
            output_path = pipeline.run_from_existing_vtt(
                script_path=request.script_path,
                vtt_path=str(vtt_path),
                output_path=request.output_path,
                fmt=request.fmt,
                use_llm_clean=request.use_llm_clean,
                track_index=request.track_index,
                vertical_mode=request.vertical_mode,
                progress_callback=progress_callback,
                debug_dir=request.debug_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return ScriptSubtitleResult(mode="from_vtt", output_path=str(output_path))

    def run_text_only(
        self,
        request: ScriptSubtitleRequest,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> ScriptSubtitleResult:
        self._validate_common(
            request,
            require_output=False,
            validate_output_format=False,
        )
        if request.output_path:
            self._ensure_output_parent(request.output_path)

        pipeline = self._build_pipeline()

        try:
            text = pipeline.run_text_only(
                script_path=request.script_path,
                output_path=request.output_path or None,
                use_llm_clean=request.use_llm_clean,
                track_index=request.track_index,
                vertical_mode=request.vertical_mode,
                progress_callback=progress_callback,
                debug_dir=request.debug_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        line_count = len([line for line in text.splitlines() if line.strip()])
        return ScriptSubtitleResult(
            mode="text_only",
            output_path=request.output_path or None,
            text=text,
            line_count=line_count,
        )

    def _build_pipeline(self):
        pipeline_class = _load_pipeline_runtime()
        return pipeline_class()

    def _validate_common(
        self,
        request: ScriptSubtitleRequest,
        *,
        require_output: bool = True,
        validate_output_format: bool = True,
    ) -> None:
        if not request.script_path:
            raise AppValidationError("script_path is required")
        if require_output and not request.output_path:
            raise AppValidationError("output_path is required")

        script_path = Path(request.script_path)
        if not script_path.exists():
            raise AppValidationError(f"script file does not exist: {request.script_path}")

        if validate_output_format and request.fmt not in _SUPPORTED_OUTPUT_FORMATS:
            raise AppValidationError(f"unsupported subtitle format: {request.fmt}")
        if request.vertical_mode not in _SUPPORTED_VERTICAL_MODES:
            raise AppValidationError(f"unsupported vertical_mode: {request.vertical_mode}")
        if request.track_index is not None and request.track_index < 0:
            raise AppValidationError("track_index must be >= 0")

    def _ensure_output_parent(self, output_path: str) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _with_default_output(request: ScriptSubtitleRequest) -> ScriptSubtitleRequest:
        if request.output_path:
            return request
        source = Path(request.script_path)
        if request.audio_path or request.vtt_path:
            filename = f"{source.stem}_aligned.{request.fmt}"
        else:
            filename = f"{source.stem}_cleaned.txt"
        return replace(request, output_path=str(source.with_name(filename)))

    def _validate_task_request(self, request: ScriptSubtitleRequest) -> None:
        self._validate_common(request)
        if request.audio_path and not Path(request.audio_path).exists():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")
        if request.vtt_path and not Path(request.vtt_path).exists():
            raise AppValidationError(f"vtt file does not exist: {request.vtt_path}")

    def _task_dependencies(self):
        if self._task_service is None or self._dispatcher is None:
            from .task_service import get_task_dispatcher, get_task_service

            self._task_service = self._task_service or get_task_service()
            self._dispatcher = self._dispatcher or get_task_dispatcher()
        if self._artifact_service is None:
            from .artifact_service import get_artifact_service

            self._artifact_service = get_artifact_service()
        return self._task_service, self._dispatcher, self._artifact_service


_service: ScriptSubtitleService | None = None
_lock = threading.Lock()


def get_script_subtitle_service() -> ScriptSubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ScriptSubtitleService()
    return _service
