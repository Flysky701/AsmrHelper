"""Application-layer facade for audio utility operations."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from ..dto import (
    ConvertRequest,
    ConvertResult,
    SeparationRequest,
    SeparationResult,
    SplitRequest,
    SplitResult,
    SplitSegment,
    SubtitleTranslationRequest,
    SubtitleTranslationResult,
    VolumePreviewRequest,
    VolumePreviewResult,
)
from ..errors import AppExecutionError, AppValidationError
from .artifact_service import ArtifactService, get_artifact_service
from .input_catalog_service import InputCatalogService, get_input_catalog_service
from .session_service import SessionService, get_session_service
from .subtitle_service import SubtitleService, get_subtitle_service
from .task_service import TaskService, get_task_service
from .workspace_service import WorkspaceService, get_workspace_service

logger = logging.getLogger(__name__)

_LANG_MAP = {
    "ja": "日文",
    "zh": "中文",
    "en": "英文",
}


class AudioToolService:
    """Stable application-facing facade for audio utility operations."""

    def __init__(
        self,
        task_service: TaskService | None = None,
        workspace_service: WorkspaceService | None = None,
        input_catalog_service: InputCatalogService | None = None,
        session_service: SessionService | None = None,
        artifact_service: ArtifactService | None = None,
        subtitle_service: SubtitleService | None = None,
    ) -> None:
        self._task_service = task_service or get_task_service()
        self._workspace_service = workspace_service or get_workspace_service()
        self._input_catalog_service = input_catalog_service or get_input_catalog_service()
        self._session_service = session_service or get_session_service()
        self._artifact_service = artifact_service or get_artifact_service()
        self._subtitle_service = subtitle_service or get_subtitle_service()

    def run_tool_task(self, task_id: str) -> dict[str, Any]:
        task_spec = self._task_service.get_task_spec(task_id)
        if not task_spec.task_type.startswith("tool."):
            raise AppValidationError(f"task is not a tool task: {task_id}")
        return self.run_tool_task_spec(task_spec)

    def run_tool_task_spec(self, task_spec) -> dict[str, Any]:
        session = self._session_service.get_session(task_spec.session_id)
        input_asset = self._input_catalog_service.get_asset(task_spec.input_asset_id)
        tool_name = task_spec.task_type.removeprefix("tool.")
        self._task_service.start_task(task_spec.task_id, message=f"running {tool_name}")

        try:
            if tool_name == "separate":
                result = self.separate_vocals(
                    SeparationRequest(
                        input_path=input_asset.absolute_path,
                        output_dir=session.resolved_output_dir,
                        model=task_spec.execution_profile.get("model", "htdemucs"),
                        stems=task_spec.execution_profile.get("stems"),
                    )
                )
                if result.primary_output:
                    self._artifact_service.register_artifact(
                        task_id=task_spec.task_id,
                        artifact_type="audio.vocals",
                        path=result.primary_output,
                        label="Separated Vocals",
                        preview_kind="audio",
                        stage="separation",
                        is_primary=True,
                    )
                detail = result.primary_output or ""
                summary = {"primary_output": result.primary_output, "stems": dict(result.stems)}
            elif tool_name == "convert":
                output_path = task_spec.execution_profile.get("output_path")
                if not output_path:
                    extension = task_spec.execution_profile.get("target_format", "wav")
                    output_path = str(Path(session.resolved_output_dir) / f"{Path(input_asset.display_name).stem}.{extension}")
                result = self.convert_audio(
                    ConvertRequest(
                        input_path=input_asset.absolute_path,
                        output_path=output_path,
                        target_format=task_spec.execution_profile.get("target_format", "wav"),
                        sample_rate=int(task_spec.execution_profile.get("sample_rate", 44100)),
                        channels=int(task_spec.execution_profile.get("channels", 2)),
                    )
                )
                self._artifact_service.register_artifact(
                    task_id=task_spec.task_id,
                    artifact_type=f"audio.{result.format}",
                    path=result.output_path,
                    label="Converted Audio",
                    preview_kind="audio",
                    stage="convert",
                    is_primary=True,
                )
                detail = result.output_path
                summary = {
                    "primary_output": result.output_path,
                    "format": result.format,
                    "sample_rate": result.sample_rate,
                    "channels": result.channels,
                    "duration": result.duration,
                }
            elif tool_name == "translate_subtitle":
                result = self.translate_subtitle(
                    SubtitleTranslationRequest(
                        input_path=input_asset.absolute_path,
                        output_path=task_spec.execution_profile.get("output_path", ""),
                        provider=task_spec.execution_profile.get("provider", "deepseek"),
                        source_lang=task_spec.execution_profile.get("source_lang", "ja"),
                        target_lang=task_spec.execution_profile.get("target_lang", "zh"),
                        bilingual=bool(task_spec.execution_profile.get("bilingual", True)),
                    )
                )
                if result.output_path:
                    self._artifact_service.register_artifact(
                        task_id=task_spec.task_id,
                        artifact_type=f"subtitle.{Path(result.output_path).suffix.lstrip('.') or 'srt'}",
                        path=result.output_path,
                        label="Translated Subtitle",
                        preview_kind="subtitle",
                        stage="translate_subtitle",
                        is_primary=True,
                    )
                detail = result.output_path or ""
                summary = {"primary_output": result.output_path, "total_segments": result.total_segments}
            elif tool_name == "split":
                subtitle_path = self._resolve_subtitle_companion(task_spec.companion_asset_ids)
                if not subtitle_path:
                    raise AppValidationError("split tool requires a subtitle companion asset")
                result = self.split_by_subtitle(
                    SplitRequest(
                        audio_path=input_asset.absolute_path,
                        subtitle_path=subtitle_path,
                        output_dir=task_spec.execution_profile.get("output_dir", session.resolved_output_dir),
                        padding=float(task_spec.execution_profile.get("padding", 0.1)),
                    )
                )
                if result.segments:
                    self._artifact_service.register_artifact(
                        task_id=task_spec.task_id,
                        artifact_type="audio.segment_collection",
                        path=result.segments[0].output_path,
                        label="Split Segments",
                        preview_kind="audio",
                        stage="split",
                        is_primary=True,
                        metadata={"total_segments": result.total_segments},
                    )
                detail = result.segments[0].output_path if result.segments else ""
                summary = {
                    "total_segments": result.total_segments,
                    "segments": [
                        {
                            "index": segment.index,
                            "start": segment.start,
                            "end": segment.end,
                            "text": segment.text,
                            "output_path": segment.output_path,
                        }
                        for segment in result.segments
                    ],
                }
            elif tool_name == "volume_preview":
                result = self.preview_volume(
                    VolumePreviewRequest(
                        audio_path=input_asset.absolute_path,
                        tts_path=task_spec.execution_profile.get("tts_path"),
                        original_volume=float(task_spec.execution_profile.get("original_volume", 0.85)),
                        tts_volume_ratio=float(task_spec.execution_profile.get("tts_volume_ratio", 0.5)),
                    )
                )
                detail = ""
                summary = {
                    "rms_volume": result.rms_volume,
                    "tts_rms_volume": result.tts_rms_volume,
                    "recommended_original_volume": result.recommended_original_volume,
                    "recommended_tts_ratio": result.recommended_tts_ratio,
                }
            else:
                raise AppValidationError(f"unsupported tool task type: {task_spec.task_type}")
        except Exception as exc:
            self._task_service.fail_task(
                task_spec.task_id,
                message=f"{tool_name} failed",
                detail=str(exc),
            )
            raise

        task = self._task_service.complete_task(
            task_spec.task_id,
            message=f"{tool_name} completed",
            detail=detail,
        )
        return {
            "task": task,
            "tool_name": tool_name,
            "summary": summary,
        }

    def create_tool_task_spec(
        self,
        *,
        task_type: str,
        input_path: str,
        execution_profile: dict[str, Any],
        companion_paths: list[str] | None = None,
        task_source: str = "legacy-tool-route",
    ):
        workspace = self._workspace_service.resolve()
        input_asset = self._input_catalog_service.inspect_paths([input_path])[0]
        companion_asset_ids: list[str] = []
        if companion_paths:
            companion_asset_ids = [
                asset.asset_id for asset in self._input_catalog_service.inspect_paths(companion_paths)
            ]
        session = self._session_service.create_session(
            workspace_id=workspace.workspace_id,
            mode="single-audio" if input_asset.kind == "audio" else "subtitle-only",
            input_asset_ids=[input_asset.asset_id],
            primary_input_asset_id=input_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            output_policy={
                "mode": "workspace-default",
                "custom_output_dir": execution_profile.get("output_dir") or None,
            },
        )
        task_spec, _ = self._task_service.create_task_spec(
            task_type=task_type,
            task_source=task_source,
            session_id=session.session_id,
            input_asset_id=input_asset.asset_id,
            companion_asset_ids=companion_asset_ids,
            execution_profile=dict(execution_profile),
        )
        return task_spec

    def _resolve_subtitle_companion(self, companion_asset_ids: list[str]) -> str | None:
        for asset_id in companion_asset_ids:
            asset = self._input_catalog_service.get_asset(asset_id)
            if asset.kind == "subtitle":
                return asset.absolute_path
        return None

    # --- Vocal Separation ---

    def separate_vocals(self, request: SeparationRequest) -> SeparationResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        source = Path(request.input_path)
        if not source.exists():
            raise AppValidationError(f"input file does not exist: {request.input_path}")

        output_dir = request.output_dir or str(source.parent)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        try:
            from src.core.vocal_separator import VocalSeparator

            separator = VocalSeparator(model_name=request.model)
            if request.stems:
                stems = separator.separate(str(source), output_dir, stems=request.stems)
            else:
                vocals_path = separator.separate_vocals(str(source), output_dir)
                stems = {"vocals": vocals_path}
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        primary = stems.get("vocals")
        return SeparationResult(
            input_path=request.input_path,
            stems=stems,
            primary_output=primary,
        )

    # --- Audio Format Conversion ---

    _SUBTYPE_MAP = {
        "wav": "PCM_16",
        "mp3": "MPEG_LAYER_III",
        "flac": "PCM_24",
        "ogg": "VORBIS",
    }

    def convert_audio(self, request: ConvertRequest) -> ConvertResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        source = Path(request.input_path)
        if not source.exists():
            raise AppValidationError(f"input file does not exist: {request.input_path}")

        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_fmt = request.target_format.lower()

        try:
            if target_fmt == "m4a":
                duration = self._convert_via_ffmpeg(
                    str(source), str(output_path), request.sample_rate, request.channels
                )
            else:
                duration = self._convert_via_soundfile(
                    str(source), str(output_path), target_fmt,
                    request.sample_rate, request.channels,
                )
        except AppValidationError:
            raise
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return ConvertResult(
            input_path=request.input_path,
            output_path=str(output_path),
            format=request.target_format,
            sample_rate=request.sample_rate,
            channels=request.channels,
            duration=duration,
        )

    @staticmethod
    def _convert_via_ffmpeg(
        input_path: str, output_path: str, sample_rate: int, channels: int
    ) -> float:
        import subprocess

        from src.utils import get_ffmpeg

        cmd = [
            get_ffmpeg(), "-y", "-i", input_path,
            "-ar", str(sample_rate), "-ac", str(channels),
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            raise AppExecutionError("ffmpeg is required for m4a conversion but was not found")

        import soundfile as sf

        info = sf.info(output_path)
        return info.duration

    def _convert_via_soundfile(
        self, input_path: str, output_path: str, target_fmt: str,
        sample_rate: int, channels: int,
    ) -> float:
        import soundfile as sf
        import numpy as np

        data, src_sr = sf.read(input_path)
        if src_sr != sample_rate:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(sample_rate, src_sr)
            data = resample_poly(data, sample_rate // g, src_sr // g)

        if data.ndim == 2 and channels == 1:
            data = data.mean(axis=1)
        elif data.ndim == 1 and channels == 2:
            data = np.column_stack([data, data])

        subtype = self._SUBTYPE_MAP.get(target_fmt)
        sf.write(output_path, data, sample_rate, format=target_fmt, subtype=subtype)
        return float(len(data)) / sample_rate

    # --- Subtitle-based Audio Splitting ---

    def split_by_subtitle(self, request: SplitRequest) -> SplitResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")
        if not request.subtitle_path:
            raise AppValidationError("subtitle_path is required")

        audio_path = Path(request.audio_path)
        subtitle_path = Path(request.subtitle_path)
        if not audio_path.exists():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")
        if not subtitle_path.exists():
            raise AppValidationError(f"subtitle file does not exist: {request.subtitle_path}")

        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            from src.core.translate import load_subtitle_with_timestamps
            import soundfile as sf

            entries = load_subtitle_with_timestamps(str(subtitle_path))
            if not entries:
                raise AppValidationError("subtitle file contains no entries")

            data, sr = sf.read(str(audio_path))
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        segments: list[SplitSegment] = []
        stem = audio_path.stem
        for i, entry in enumerate(entries):
            start = max(0.0, float(entry.get("start", 0.0)) - request.padding)
            end = float(entry.get("end", 0.0)) + request.padding
            text = str(entry.get("text", ""))

            start_sample = int(start * sr)
            end_sample = min(int(end * sr), len(data))
            chunk = data[start_sample:end_sample]

            out_file = output_dir / f"{stem}_{i:04d}.wav"
            sf.write(str(out_file), chunk, sr)

            segments.append(SplitSegment(
                index=i,
                start=start,
                end=end,
                text=text,
                output_path=str(out_file),
            ))

        return SplitResult(
            audio_path=request.audio_path,
            subtitle_path=request.subtitle_path,
            segments=segments,
            total_segments=len(segments),
        )

    # --- Subtitle Translation (with timestamps) ---

    def translate_subtitle(self, request: SubtitleTranslationRequest) -> SubtitleTranslationResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")
        source = Path(request.input_path)
        if not source.exists():
            raise AppValidationError(f"subtitle file does not exist: {request.input_path}")

        try:
            from src.core.translate import (
                Translator,
                load_subtitle_with_timestamps,
                load_and_clean_subtitle,
            )

            entries = load_and_clean_subtitle(str(source))
            if not entries:
                raise AppValidationError("subtitle file contains no entries")

            translator = Translator(provider=request.provider)
            source_label = _LANG_MAP.get(request.source_lang, request.source_lang)
            target_label = _LANG_MAP.get(request.target_lang, request.target_lang)
            segments = translator.translate_segments(
                entries,
                source_lang=source_label,
                target_lang=target_label,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        output_path = request.output_path
        if not output_path:
            output_path = str(source.with_stem(source.stem + f"_{request.target_lang}"))

        try:
            self._subtitle_service.export_bilingual_subtitle(segments, output_path, request.bilingual)
        except Exception as exc:
            raise AppExecutionError(f"failed to write output subtitle: {exc}") from exc

        return SubtitleTranslationResult(
            input_path=request.input_path,
            output_path=output_path,
            total_segments=len(segments),
            provider=request.provider,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )

    # --- Volume Preview ---

    def preview_volume(self, request: VolumePreviewRequest) -> VolumePreviewResult:
        if not request.audio_path:
            raise AppValidationError("audio_path is required")
        source = Path(request.audio_path)
        if not source.exists():
            raise AppValidationError(f"audio file does not exist: {request.audio_path}")

        try:
            from src.mixer import Mixer

            mixer = Mixer()
            rms = mixer.detect_volume(str(source))

            tts_rms = None
            if request.tts_path:
                tts_source = Path(request.tts_path)
                if tts_source.exists():
                    tts_rms = mixer.detect_volume(str(tts_source))
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        recommended_ratio = request.tts_volume_ratio
        if rms > 0 and tts_rms and tts_rms > 0:
            recommended_ratio = min(1.0, rms / tts_rms * 0.6)

        return VolumePreviewResult(
            audio_path=request.audio_path,
            rms_volume=rms,
            tts_rms_volume=tts_rms,
            recommended_original_volume=request.original_volume,
            recommended_tts_ratio=round(recommended_ratio, 3),
        )



_service: AudioToolService | None = None
_lock = threading.Lock()


def get_audio_tool_service() -> AudioToolService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = AudioToolService()
    return _service
