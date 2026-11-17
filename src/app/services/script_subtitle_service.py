"""Application-layer wrapper for script-to-subtitle workflows."""

from __future__ import annotations

import threading
import json
import uuid
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

    def __init__(
        self, *, task_service=None, dispatcher=None, artifact_service=None
    ) -> None:
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
            "confirmed_text": request.confirmed_text,
            "fingerprint": request.fingerprint,
            "use_llm_match": request.use_llm_match,
            "reference_confirmed": request.reference_confirmed,
        }
        companion_paths = [
            path for path in (request.audio_path, request.vtt_path) if path
        ]
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
            use_llm_clean=bool(profile.get("use_llm_clean", False)),
            asr_model_size=str(profile.get("asr_model_size") or "large-v3"),
            asr_language=str(profile.get("asr_language") or "ja"),
            track_index=profile.get("track_index"),
            vertical_mode=str(profile.get("vertical_mode") or "auto"),
            debug_dir=profile.get("debug_dir") or None,
            confirmed_text=profile.get("confirmed_text"),
            fingerprint=profile.get("fingerprint"),
            use_llm_match=bool(profile.get("use_llm_match", False)),
            reference_confirmed=bool(profile.get("reference_confirmed", False)),
        )
        # The retry specification may refer to the old attempt; never reuse its files.
        requested = Path(request.output_path)
        attempt = requested.parent / f"{task_spec.task_id}-{uuid.uuid4().hex[:8]}"
        request = replace(request, output_path=str(attempt / requested.name))

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

        try:
            if request.vtt_path:
                result = self.run_from_existing_vtt(request, progress_callback=progress)
            elif request.audio_path:
                result = self.run_full(request, progress_callback=progress)
            else:
                result = self.run_text_only(request, progress_callback=progress)
        finally:
            report_path = Path(request.output_path).with_suffix(".review.json")
            if report_path.is_file() and not context.cancellation_requested:
                _, _, artifacts = self._task_dependencies()
                artifacts.register_artifact(
                    task_id=task_spec.task_id,
                    artifact_type="analysis.script_review",
                    path=str(report_path),
                    label="台本匹配核对报告",
                    preview_kind="json",
                    stage="llm_align",
                    is_primary=False,
                )

        if context.cancellation_requested:
            raise RuntimeError("cancelled by user")
        if not result.output_path:
            raise AppExecutionError("script subtitle task produced no output")

        _, _, artifact_service = self._task_dependencies()
        artifact_service.register_artifact(
            task_id=task_spec.task_id,
            artifact_type="subtitle.txt"
            if result.mode == "text_only"
            else f"subtitle.{request.fmt}",
            path=result.output_path,
            label="Cleaned Script"
            if result.mode == "text_only"
            else "Script Subtitle Output",
            preview_kind="subtitle",
            stage="script_to_subtitle",
            is_primary=True,
            metadata={"mode": result.mode, "line_count": result.line_count},
        )
        context.update_progress(
            1.0, message="台本转字幕完成", stage="script_to_subtitle"
        )
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
        self.validate_confirmed_request(request)
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
                confirmed_text=request.confirmed_text,
                fingerprint=request.fingerprint,
                use_llm_match=request.use_llm_match,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return ScriptSubtitleResult(
            mode="full",
            output_path=str(output_path),
            line_count=self._subtitle_count(output_path),
        )

    def run_from_existing_vtt(
        self,
        request: ScriptSubtitleRequest,
        progress_callback: Callable[[str, int, str], None] | None = None,
    ) -> ScriptSubtitleResult:
        self._validate_common(request)
        if not request.vtt_path:
            raise AppValidationError("vtt_path is required")
        self.validate_confirmed_request(request)
        if not request.reference_confirmed:
            raise AppValidationError(
                "请确认参考字幕是同一录音的同语言原文，译文不能作为原文锚点"
            )
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
                confirmed_text=request.confirmed_text,
                fingerprint=request.fingerprint,
                use_llm_match=request.use_llm_match,
                audio_path=request.audio_path,
                asr_language=request.asr_language,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return ScriptSubtitleResult(
            mode="from_vtt",
            output_path=str(output_path),
            line_count=self._subtitle_count(output_path),
        )

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
                confirmed_text=request.confirmed_text,
                fingerprint=request.fingerprint,
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
            raise AppValidationError(
                f"script file does not exist: {request.script_path}"
            )
        if not script_path.is_file() or script_path.suffix.lower() not in {
            ".pdf",
            ".txt",
        }:
            raise AppValidationError("台本需要PDF或UTF-8 TXT文件")
        if request.output_path and any(
            Path(request.output_path).resolve() == Path(p).resolve()
            for p in (request.script_path, request.audio_path, request.vtt_path)
            if p
        ):
            raise AppValidationError("输出不能覆盖输入文件")
        if request.output_path and Path(request.output_path).exists():
            raise AppValidationError("输出文件已存在，请使用新文件名")
        if request.vtt_path and not request.reference_confirmed:
            raise AppValidationError(
                "请确认参考字幕是同一录音的同语言原文，译文不能作为原文锚点"
            )
        if (request.audio_path or request.vtt_path) and request.asr_language not in {
            "ja",
            "zh",
            "en",
        }:
            raise AppValidationError("请选择日语、中文或英语原文语言")

        if validate_output_format and request.fmt not in _SUPPORTED_OUTPUT_FORMATS:
            raise AppValidationError(f"unsupported subtitle format: {request.fmt}")
        if request.vertical_mode not in _SUPPORTED_VERTICAL_MODES:
            raise AppValidationError(
                f"unsupported vertical_mode: {request.vertical_mode}"
            )
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
        return replace(
            request, output_path=str(source.parent / ".asmr-script" / filename)
        )

    def _validate_task_request(self, request: ScriptSubtitleRequest) -> None:
        self._validate_common(request)
        self.validate_confirmed_request(request)
        if request.vtt_path and not request.reference_confirmed:
            raise AppValidationError(
                "请确认参考字幕是同一录音的同语言原文，译文不能作为原文锚点"
            )
        if request.confirmed_text is not None:
            if not request.confirmed_text.strip() or not request.fingerprint:
                raise AppValidationError("请重新预览并确认台词")
            from src.core.subtitles.script_review import script_fingerprint

            if script_fingerprint(request.script_path) != request.fingerprint:
                raise AppValidationError("台本文件已改变，请重新预览")
        if request.audio_path and not Path(request.audio_path).exists():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")
        if request.vtt_path and not Path(request.vtt_path).exists():
            raise AppValidationError(f"vtt file does not exist: {request.vtt_path}")

    def validate_confirmed_request(self, request: ScriptSubtitleRequest) -> None:
        if request.audio_path or request.vtt_path:
            if (
                request.confirmed_text is None
                or not request.confirmed_text.strip()
                or not request.fingerprint
            ):
                raise AppValidationError("请先预览、修订并确认台词")
            if not request.audio_path:
                raise AppValidationError("请提供对应录音，以核实时长和试听修正")
            from src.core.subtitles.script_review import script_fingerprint

            if script_fingerprint(request.script_path) != request.fingerprint:
                raise AppValidationError("台本文件已改变，请重新预览并确认")

    @staticmethod
    def _subtitle_count(path) -> int:
        report_path = Path(path).with_suffix(".review.json")
        return (
            len(json.loads(report_path.read_text(encoding="utf-8")).get("entries", []))
            if report_path.is_file()
            else 0
        )

    def preview(self, request: ScriptSubtitleRequest) -> dict:
        self._validate_common(
            request, require_output=False, validate_output_format=False
        )
        try:
            return self._build_pipeline().preview(
                request.script_path,
                track_index=request.track_index,
                vertical_mode=request.vertical_mode,
                use_llm_clean=request.use_llm_clean,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            raise AppValidationError(str(exc)) from exc

    def review(self, task_id: str) -> dict | None:
        tasks, _, artifacts = self._task_dependencies()
        if tasks.get_task_spec(task_id).task_type != "subtitle.script_to_vtt":
            raise AppValidationError("不是台本字幕任务")
        for artifact in artifacts.get_task_artifacts(task_id).entries:
            if (
                artifact.artifact_type == "analysis.script_review"
                and artifact.task_id == task_id
            ):
                return json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        return None

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
