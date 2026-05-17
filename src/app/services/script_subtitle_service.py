"""Application-layer wrapper for script-to-subtitle workflows."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from ..dto.script_subtitle import ScriptSubtitleRequest, ScriptSubtitleResult
from ..errors import AppExecutionError, AppValidationError

_SUPPORTED_OUTPUT_FORMATS = frozenset({"vtt", "srt", "lrc"})
_SUPPORTED_VERTICAL_MODES = frozenset({"auto", "horizontal", "vertical"})

ScriptToSubtitlePipeline = None


def _load_pipeline_runtime():
    global ScriptToSubtitlePipeline
    if ScriptToSubtitlePipeline is None:
        from src.core.script_to_subtitle import ScriptToSubtitlePipeline as core_pipeline

        ScriptToSubtitlePipeline = core_pipeline
    return ScriptToSubtitlePipeline


class ScriptSubtitleService:
    """Stable facade over the core ScriptToSubtitlePipeline."""

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


_service: ScriptSubtitleService | None = None
_lock = threading.Lock()


def get_script_subtitle_service() -> ScriptSubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = ScriptSubtitleService()
    return _service
