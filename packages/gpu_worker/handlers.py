"""Stateless GPU execution adapters for separation, ASR, forced alignment, and TTS.

This module bridges `packages.protocol` contracts to underlying inference engines
(or injected unit-test callbacks) under `ModelLeaseManager` VRAM protection.
It MUST remain 100% stateless: zero SQLite, `DraftSession`, or user-account imports.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
import io
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import uuid

import numpy as np
import soundfile as sf

from packages.protocol.compute import (
    AlignmentRequest,
    AlignmentResult,
    AlignmentWordItem,
    AsrRequest,
    AsrResult,
    AsrSegmentItem,
    AudioFormat,
    SeparationRequest,
    SeparationResult,
    TtsBatchItemResult,
    TtsBatchRequest,
    TtsBatchResult,
    TtsSynthesizeItem,
)
from packages.protocol.errors import (
    ComputeErrorCode,
    ComputeErrorPayload,
    ComputeRemoteError,
)

from .vram_lease import ModelLeaseManager

_SAFE_AUDIO_EXTENSIONS = {".flac", ".wav", ".ogg", ".mp3", ".m4a", ".aac"}


def _sniff_extension(audio_bytes: bytes, filename_hint: str | None = None) -> str:
    if audio_bytes.startswith(b"fLaC"):
        return ".flac"
    if audio_bytes.startswith(b"RIFF"):
        return ".wav"
    if audio_bytes.startswith(b"OggS"):
        return ".ogg"
    if filename_hint:
        ext = Path(filename_hint).suffix.lower()
        if ext in _SAFE_AUDIO_EXTENSIONS:
            return ext
    return ".flac"


def _ffmpeg_decode_to_wav(src_path: Path, dst_wav: Path) -> bool:
    """Fallback decoder via imageio-ffmpeg when libsndfile cannot read container."""
    try:
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

    try:
        completed = subprocess.run(
            [
                ffmpeg_exe,
                "-y",
                "-v",
                "error",
                "-i",
                str(src_path),
                "-vn",
                "-acodec",
                "pcm_f32le",
                str(dst_wav),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        return completed.returncode == 0 and dst_wav.is_file() and dst_wav.stat().st_size > 44
    except Exception:
        return False


def decode_audio_bytes_to_file(
    audio_bytes: bytes,
    target_dir: Path,
    *,
    filename_hint: str | None = None,
    stage: str = "audio",
) -> tuple[Path, int, float]:
    """Safely materialize and validate uploaded audio bytes into `target_dir`."""
    if not audio_bytes:
        raise ComputeRemoteError(
            code=ComputeErrorCode.AUDIO_DECODE_ERROR,
            message="Uploaded audio payload is empty",
            retryable=False,
            stage=stage,
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    ext = _sniff_extension(audio_bytes, filename_hint)
    staged_path = target_dir / f"payload_{uuid.uuid4().hex[:10]}{ext}"
    staged_path.write_bytes(audio_bytes)

    try:
        info = sf.info(str(staged_path))
        if info.samplerate <= 0 or info.frames <= 0:
            raise ValueError("decoded audio has zero frames or invalid sample rate")
        return staged_path, int(info.samplerate), float(info.duration)
    except Exception as primary_exc:
        fallback_wav = target_dir / f"decoded_{uuid.uuid4().hex[:10]}.wav"
        if _ffmpeg_decode_to_wav(staged_path, fallback_wav):
            staged_path.unlink(missing_ok=True)
            info = sf.info(str(fallback_wav))
            return fallback_wav, int(info.samplerate), float(info.duration)
        staged_path.unlink(missing_ok=True)
        raise ComputeRemoteError(
            code=ComputeErrorCode.AUDIO_DECODE_ERROR,
            message=f"Failed to decode audio payload: {primary_exc}",
            retryable=False,
            stage=stage,
        ) from primary_exc


def encode_audio_file_bytes(
    path: str | Path,
    fmt: AudioFormat = "flac",
    *,
    stage: str = "audio",
) -> tuple[bytes, int, float]:
    """Encode a local audio file into lossless FLAC or WAV bytes."""
    source = Path(path)
    if not source.is_file():
        raise ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=f"Audio file does not exist: {source}",
            retryable=False,
            stage=stage,
        )

    work_file = source
    temp_decoded: Path | None = None
    try:
        try:
            info = sf.info(str(work_file))
        except Exception as exc:
            fd_dir = Path(tempfile.gettempdir())
            candidate = fd_dir / f"transcode_{uuid.uuid4().hex[:10]}.wav"
            if not _ffmpeg_decode_to_wav(work_file, candidate):
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR,
                    message=f"Cannot read input audio {source.name}: {exc}",
                    retryable=False,
                    stage=stage,
                ) from exc
            temp_decoded = candidate
            work_file = candidate
            info = sf.info(str(work_file))

        if fmt == "flac" and work_file.suffix.lower() == ".flac":
            return work_file.read_bytes(), int(info.samplerate), float(info.duration)

        samples, sr = sf.read(str(work_file), dtype="float32", always_2d=False)
        buf = io.BytesIO()
        if fmt == "flac":
            subtype = "PCM_16" if info.subtype == "PCM_16" else "PCM_24"
            sf.write(buf, samples, sr, format="FLAC", subtype=subtype)
        else:
            subtype = info.subtype if info.subtype in {"PCM_16", "PCM_24", "FLOAT"} else "PCM_16"
            sf.write(buf, samples, sr, format="WAV", subtype=subtype)
        duration = float(len(samples) / sr) if sr > 0 else 0.0
        return buf.getvalue(), int(sr), duration
    finally:
        if temp_decoded is not None:
            temp_decoded.unlink(missing_ok=True)


def materialize_audio_bytes_to_path(
    audio_bytes: bytes,
    target_path: str | Path,
    *,
    stage: str = "audio",
    wav_subtype: str | None = None,
) -> tuple[int, float]:
    """Decode lossless FLAC/WAV bytes and write to `target_path` matching its extension."""
    if not audio_bytes:
        raise ComputeRemoteError(
            code=ComputeErrorCode.AUDIO_DECODE_ERROR,
            message="Returned audio payload is empty",
            retryable=False,
            stage=stage,
        )

    dest = Path(target_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = sf.info(io.BytesIO(audio_bytes))
        samples, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)
    except Exception as exc:
        raise ComputeRemoteError(
            code=ComputeErrorCode.AUDIO_DECODE_ERROR,
            message=f"Failed to decode returned audio payload: {exc}",
            retryable=False,
            stage=stage,
        ) from exc

    if info.frames <= 0 or sr <= 0 or not np.isfinite(samples).all():
        raise ComputeRemoteError(
            code=ComputeErrorCode.AUDIO_DECODE_ERROR,
            message="Returned audio payload has empty or non-finite samples",
            retryable=False,
            stage=stage,
        )

    ext = dest.suffix.lower()
    if ext == ".flac" and audio_bytes.startswith(b"fLaC"):
        dest.write_bytes(audio_bytes)
    elif ext == ".wav" and audio_bytes.startswith(b"RIFF") and wav_subtype is None:
        dest.write_bytes(audio_bytes)
    elif ext == ".flac":
        subtype = "PCM_16" if info.subtype == "PCM_16" else "PCM_24"
        sf.write(str(dest), samples, sr, format="FLAC", subtype=subtype)
    else:
        subtype = (
            wav_subtype
            if wav_subtype is not None
            else (info.subtype if info.subtype in {"PCM_16", "PCM_24", "FLOAT"} else "PCM_24")
        )
        sf.write(str(dest), samples, sr, format="WAV", subtype=subtype)

    duration = float(len(samples) / sr) if sr > 0 else 0.0
    return int(sr), duration


def _format_srt_ts(seconds: float) -> str:
    ms_total = max(0, round(float(seconds) * 1000))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_segments_srt(segments: list[AsrSegmentItem], output_path: str | Path) -> None:
    """Write `AsrSegmentItem` cues to a standard UTF-8 `.srt` subtitle file."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for idx, seg in enumerate(segments, start=1):
        blocks.append(
            f"{idx}\n{_format_srt_ts(seg.start)} --> {_format_srt_ts(seg.end)}\n{seg.text.strip()}\n"
        )
    target.write_text("\n".join(blocks), encoding="utf-8")


def classify_compute_exception(exc: Exception, stage: str) -> ComputeRemoteError:
    """Map runtime exceptions into structured `ComputeRemoteError` instances."""
    if isinstance(exc, ComputeRemoteError):
        return exc
    msg = str(exc) or type(exc).__name__
    lowered = msg.lower()
    if isinstance(exc, MemoryError) or "out of memory" in lowered or "cuda error: out of memory" in lowered:
        return ComputeRemoteError(
            code=ComputeErrorCode.OOM_ERROR,
            message=msg,
            retryable=True,
            stage=stage,
        )
    if isinstance(exc, (FileNotFoundError, ValueError)):
        return ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=msg,
            retryable=False,
            stage=stage,
        )
    if (
        isinstance(exc, ImportError)
        or "not installed" in lowered
        or "未准备完整" in msg
        or "请先在模型管理中安装" in msg
    ):
        return ComputeRemoteError(
            code=ComputeErrorCode.MODEL_NOT_AVAILABLE,
            message=msg,
            retryable=False,
            stage=stage,
        )
    return ComputeRemoteError(
        code=ComputeErrorCode.EXECUTION_ERROR,
        message=msg,
        retryable=False,
        stage=stage,
    )


class _UnloadableHandle:
    """Wraps an arbitrary engine or callback so `ModelLeaseManager` can unload cleanly."""

    def __init__(self, target: Any, on_unload: Callable[[], None] | None = None) -> None:
        self.target = target
        self._on_unload = on_unload

    def unload(self) -> None:
        if self._on_unload is not None:
            self._on_unload()
        if hasattr(self.target, "unload") and callable(self.target.unload):
            self.target.unload()
        self.target = None


def _safe_stem_prefix(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " _-()" else "_" for c in Path(name).stem)
    return cleaned.strip() or "audio"


class WorkerHandlers:
    """Stateless GPU task dispatcher backed by `ModelLeaseManager`."""

    def __init__(
        self,
        lease_manager: ModelLeaseManager | None = None,
        *,
        separate_fn: Callable[..., dict[str, str]] | None = None,
        asr_fn: Callable[..., list[dict[str, Any]] | AsrResult] | None = None,
        align_fn: Callable[..., dict[str, Any] | AlignmentResult] | None = None,
        tts_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.lease_manager = lease_manager or ModelLeaseManager()
        self._separate_fn = separate_fn
        self._asr_fn = asr_fn
        self._align_fn = align_fn
        self._tts_fn = tts_fn

    def _resolve_input_audio(
        self,
        *,
        input_path: str | None,
        audio_b64: str | None,
        audio_filename: str | None,
        audio_bytes: bytes | None,
        temp_dir: Path,
        stage: str,
    ) -> Path:
        raw = audio_bytes
        if raw is None and audio_b64:
            try:
                raw = base64.b64decode(audio_b64, validate=True)
            except Exception as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR,
                    message=f"Invalid base64 audio payload: {exc}",
                    retryable=False,
                    stage=stage,
                ) from exc

        if raw is not None:
            staged, _sr, _dur = decode_audio_bytes_to_file(
                raw,
                temp_dir,
                filename_hint=audio_filename or input_path,
                stage=stage,
            )
            return staged

        if not input_path:
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message="Either uploaded audio bytes, audio_b64, or input_path is required",
                retryable=False,
                stage=stage,
            )
        local_path = Path(input_path)
        if not local_path.is_file():
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message=f"Input audio path does not exist: {input_path}",
                retryable=False,
                stage=stage,
            )
        return local_path

    def separate(
        self,
        request: SeparationRequest,
        *,
        audio_bytes: bytes | None = None,
        include_audio_b64: bool = False,
    ) -> SeparationResult:
        """Execute Demucs source separation statelessly."""
        stage = "separate"
        try:
            with tempfile.TemporaryDirectory(prefix="gpu-sep-") as tmp:
                tmp_dir = Path(tmp)
                src_audio = self._resolve_input_audio(
                    input_path=request.input_path,
                    audio_b64=request.audio_b64,
                    audio_filename=request.audio_filename,
                    audio_bytes=audio_bytes,
                    temp_dir=tmp_dir,
                    stage=stage,
                )
                out_dir = Path(request.output_dir) if request.output_dir else (tmp_dir / "stems")
                out_dir.mkdir(parents=True, exist_ok=True)

                lease_key = f"separate:{request.model}"
                if self._separate_fn is not None:
                    with self.lease_manager.lease(
                        lease_key,
                        lambda: _UnloadableHandle(self._separate_fn),
                        family="separate",
                    ) as handle:
                        raw_stems = handle.target(
                            input_path=str(src_audio),
                            output_dir=str(out_dir),
                            model=request.model,
                            stems=list(request.stems),
                        )
                else:
                    raw_stems = self._run_demucs_separation(
                        lease_key=lease_key,
                        model_name=request.model,
                        src_audio=src_audio,
                        out_dir=out_dir,
                        requested_stems=list(request.stems),
                    )

                stem_paths: dict[str, str] = {}
                stem_b64: dict[str, str] = {}
                sample_rate: int | None = None
                duration_sec: float | None = None

                for stem_name, file_path in raw_stems.items():
                    p = Path(file_path)
                    if request.output_dir:
                        if request.output_format == "flac" and p.suffix.lower() != ".flac":
                            flac_bytes, sr, dur = encode_audio_file_bytes(p, "flac", stage=stage)
                            flac_target = p.with_suffix(".flac")
                            flac_target.write_bytes(flac_bytes)
                            p.unlink(missing_ok=True)
                            p = flac_target
                            sample_rate, duration_sec = sr, dur
                        stem_paths[stem_name] = str(p)

                    if include_audio_b64 or not request.output_dir:
                        encoded, sr, dur = encode_audio_file_bytes(
                            p, request.output_format, stage=stage
                        )
                        stem_b64[stem_name] = base64.b64encode(encoded).decode("ascii")
                        sample_rate, duration_sec = sr, dur
                    elif sample_rate is None and p.is_file():
                        info = sf.info(str(p))
                        sample_rate = int(info.samplerate)
                        duration_sec = float(info.duration)

                return SeparationResult(
                    model=request.model,
                    stem_paths=stem_paths,
                    stem_audio_b64=stem_b64 if include_audio_b64 else {},
                    output_format=request.output_format,
                    sample_rate=sample_rate,
                    duration_seconds=duration_sec,
                )
        except Exception as exc:
            raise classify_compute_exception(exc, stage) from exc

    def _run_demucs_separation(
        self,
        *,
        lease_key: str,
        model_name: str,
        src_audio: Path,
        out_dir: Path,
        requested_stems: list[str],
    ) -> dict[str, str]:
        def _load_separator() -> Any:
            from src.core.vocal_separator import VocalSeparator

            return VocalSeparator(model_name=model_name, progress=False)

        wants_no_vocals = "no_vocals" in requested_stems
        demucs_stems = [s for s in requested_stems if s != "no_vocals"]
        if wants_no_vocals:
            for bg_stem in ("drums", "bass", "other"):
                if bg_stem not in demucs_stems:
                    demucs_stems.append(bg_stem)

        with self.lease_manager.lease(lease_key, _load_separator, family="separate") as separator:
            produced = dict(separator.separate(str(src_audio), str(out_dir), stems=demucs_stems))

        if wants_no_vocals and "no_vocals" not in produced:
            bg_arrays: list[np.ndarray] = []
            sr = 44100
            for bg_stem in ("drums", "bass", "other"):
                stem_file = produced.get(bg_stem)
                if stem_file and Path(stem_file).is_file():
                    arr, sr = sf.read(stem_file, dtype="float32", always_2d=True)
                    bg_arrays.append(arr)
            if bg_arrays:
                min_len = min(a.shape[0] for a in bg_arrays)
                mixed_bg = sum(a[:min_len] for a in bg_arrays)
                no_vocals_path = out_dir / f"{_safe_stem_prefix(src_audio.name)}_no_vocals.wav"
                sf.write(str(no_vocals_path), mixed_bg, sr, subtype="FLOAT")
                produced["no_vocals"] = str(no_vocals_path)
            for extra in ("drums", "bass", "other"):
                if extra not in requested_stems and extra in produced:
                    Path(produced.pop(extra)).unlink(missing_ok=True)

        return {k: v for k, v in produced.items() if k in requested_stems}

    def asr(
        self,
        request: AsrRequest,
        *,
        audio_bytes: bytes | None = None,
    ) -> AsrResult:
        """Execute stateless ASR transcription."""
        stage = "asr"
        try:
            with tempfile.TemporaryDirectory(prefix="gpu-asr-") as tmp:
                tmp_dir = Path(tmp)
                src_audio = self._resolve_input_audio(
                    input_path=request.input_path,
                    audio_b64=request.audio_b64,
                    audio_filename=request.audio_filename,
                    audio_bytes=audio_bytes,
                    temp_dir=tmp_dir,
                    stage=stage,
                )
                duration_sec: float | None = None
                try:
                    duration_sec = float(sf.info(str(src_audio)).duration)
                except Exception:
                    duration_sec = None

                lease_key = f"asr:{request.provider}:{request.model or 'default'}"
                if self._asr_fn is not None:
                    with self.lease_manager.lease(
                        lease_key,
                        lambda: _UnloadableHandle(self._asr_fn),
                        family="asr",
                    ) as handle:
                        raw_res = handle.target(input_path=str(src_audio), request=request)
                    result = self._normalize_asr_output(
                        raw_res, request=request, duration_seconds=duration_sec
                    )
                else:
                    result = self._run_engine_asr(
                        lease_key=lease_key,
                        src_audio=src_audio,
                        request=request,
                        duration_seconds=duration_sec,
                    )

                if request.output_path:
                    write_segments_srt(result.segments, request.output_path)
                    result.source_path = str(request.output_path)
                    result.format = "srt"
                return result
        except Exception as exc:
            raise classify_compute_exception(exc, stage) from exc

    @staticmethod
    def _normalize_asr_output(
        raw: list[dict[str, Any]] | AsrResult,
        *,
        request: AsrRequest,
        duration_seconds: float | None,
    ) -> AsrResult:
        if isinstance(raw, AsrResult):
            if raw.duration_seconds is None and duration_seconds is not None:
                raw.duration_seconds = duration_seconds
            if not raw.provider:
                raw.provider = request.provider
            if not raw.model:
                raw.model = request.model
            return raw

        segments: list[AsrSegmentItem] = []
        for entry in raw:
            start = max(0.0, float(entry.get("start", 0.0) or 0.0))
            end = max(start, float(entry.get("end", start) or start))
            conf_raw = entry.get("confidence")
            conf = float(conf_raw) if conf_raw is not None and math.isfinite(float(conf_raw)) else None
            meta = dict(entry.get("recognition_metadata") or {})
            meta.setdefault("provider", request.provider)
            segments.append(
                AsrSegmentItem(
                    start=start,
                    end=end,
                    text=str(entry.get("text", "")),
                    language=str(entry.get("language") or request.language),
                    confidence=conf,
                    recognition_metadata=meta,
                )
            )
        return AsrResult(
            segments=segments,
            language=request.language,
            provider=request.provider,
            model=request.model,
            duration_seconds=duration_seconds,
        )

    def _run_engine_asr(
        self,
        *,
        lease_key: str,
        src_audio: Path,
        request: AsrRequest,
        duration_seconds: float | None,
    ) -> AsrResult:
        from src.core.engines.asr.registry import AsrRegistry
        from src.core.engines.asr.service import AsrEngineRuntime

        profile = request.to_profile()
        provider = str(profile["provider"])
        common_options = dict(profile.get("common_options") or {})
        provider_options = dict(profile.get("provider_options") or {})

        def _load_recognizer() -> Any:
            isolated_registry = AsrRegistry()
            isolated_registry._register_builtins()
            kwargs = AsrEngineRuntime._build_provider_kwargs(
                provider=provider,
                model=str(profile.get("model") or ""),
                common_options=common_options,
                provider_options=provider_options,
            )
            return isolated_registry.get(provider, **kwargs)

        recognize_kwargs: dict[str, Any] = {}
        if provider == "faster_whisper" and provider_options.get("preserve_segments"):
            recognize_kwargs.update(preserve_segments=True, min_segment_duration=0.0)
        if provider == "faster_whisper" and "vad_filter" in provider_options:
            recognize_kwargs["vad_filter"] = bool(provider_options["vad_filter"])
        if provider == "anime_whisper":
            if provider_options.get("vad_slicing") is not None:
                recognize_kwargs["vad_slicing"] = bool(provider_options["vad_slicing"])
            elif provider_options.get("vad_filter") is not None:
                recognize_kwargs["vad_filter"] = bool(provider_options["vad_filter"])

        with self.lease_manager.lease(lease_key, _load_recognizer, family="asr") as recognizer:
            entries = recognizer.recognize(str(src_audio), None, **recognize_kwargs)

        return self._normalize_asr_output(
            entries, request=request, duration_seconds=duration_seconds
        )

    def align(
        self,
        request: AlignmentRequest,
        *,
        audio_bytes: bytes | None = None,
    ) -> AlignmentResult:
        """Execute stateless forced alignment."""
        stage = "align"
        try:
            with tempfile.TemporaryDirectory(prefix="gpu-align-") as tmp:
                tmp_dir = Path(tmp)
                src_audio = self._resolve_input_audio(
                    input_path=request.input_path,
                    audio_b64=request.audio_b64,
                    audio_filename=request.audio_filename,
                    audio_bytes=audio_bytes,
                    temp_dir=tmp_dir,
                    stage=stage,
                )
                lease_key = f"align:{request.model}"
                if self._align_fn is not None:
                    with self.lease_manager.lease(
                        lease_key,
                        lambda: _UnloadableHandle(self._align_fn),
                        family="align",
                    ) as handle:
                        raw_aligned = handle.target(input_path=str(src_audio), request=request)
                    if isinstance(raw_aligned, AlignmentResult):
                        return raw_aligned
                    return AlignmentResult(
                        segments=list(raw_aligned.get("segments") or []),
                        words=[
                            AlignmentWordItem.model_validate(w)
                            for w in (raw_aligned.get("words") or [])
                        ],
                        warnings=[str(w) for w in (raw_aligned.get("warnings") or [])],
                        model=str(raw_aligned.get("model") or request.model),
                        time_unit=str(raw_aligned.get("time_unit") or "seconds"),
                    )

                def _load_aligner() -> _UnloadableHandle:
                    from src.core.engines.alignment import AlignmentRuntime

                    align_model = AlignmentRuntime._load_model()
                    return _UnloadableHandle(align_model)

                with self.lease_manager.lease(lease_key, _load_aligner, family="align") as handle:
                    from src.core.engines.alignment import AlignmentRuntime

                    runtime_out = AlignmentRuntime(local=True, model=handle.target).align_file(
                        input_path=str(src_audio),
                        segments=request.segments,
                        language=request.language,
                    )
                return AlignmentResult(
                    segments=list(runtime_out.get("segments") or []),
                    words=[
                        AlignmentWordItem.model_validate(w)
                        for w in (runtime_out.get("words") or [])
                    ],
                    warnings=[str(w) for w in (runtime_out.get("warnings") or [])],
                    model=str(runtime_out.get("model") or request.model),
                    time_unit=str(runtime_out.get("time_unit") or "seconds"),
                )
        except Exception as exc:
            raise classify_compute_exception(exc, stage) from exc

    def tts_batch(
        self,
        request: TtsBatchRequest,
        *,
        reference_audio_bytes: bytes | None = None,
        include_audio_b64: bool = False,
    ) -> TtsBatchResult:
        """Execute stateless batch TTS synthesis."""
        stage = "tts_batch"
        try:
            with tempfile.TemporaryDirectory(prefix="gpu-tts-") as tmp:
                tmp_dir = Path(tmp)
                resolved_refs = self._stage_tts_references(
                    request=request,
                    reference_audio_bytes=reference_audio_bytes,
                    temp_dir=tmp_dir,
                    stage=stage,
                )

                lease_key = f"tts:{request.provider_id}:{request.model or 'default'}"
                if self._tts_fn is not None:
                    with self.lease_manager.lease(
                        lease_key,
                        lambda: _UnloadableHandle(self._tts_fn),
                        family="tts",
                    ) as handle:
                        items_out = [
                            self._run_callback_tts_item(
                                fn=handle.target,
                                item=item,
                                request=request,
                                resolved_refs=resolved_refs,
                                temp_dir=tmp_dir,
                                include_audio_b64=include_audio_b64,
                            )
                            for item in request.items
                        ]
                else:
                    items_out = self._run_engine_tts_batch(
                        lease_key=lease_key,
                        request=request,
                        resolved_refs=resolved_refs,
                        temp_dir=tmp_dir,
                        include_audio_b64=include_audio_b64,
                    )

                return TtsBatchResult(
                    provider_id=request.provider_id,
                    model=request.model,
                    output_format=request.output_format,
                    items=items_out,
                )
        except Exception as exc:
            raise classify_compute_exception(exc, stage) from exc

    def _stage_tts_references(
        self,
        *,
        request: TtsBatchRequest,
        reference_audio_bytes: bytes | None,
        temp_dir: Path,
        stage: str,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for ref_id, local_ref in request.references.items():
            p = Path(local_ref)
            if not p.is_file():
                raise ComputeRemoteError(
                    code=ComputeErrorCode.INVALID_REQUEST,
                    message=f"Reference audio {ref_id!r} not found at {local_ref}",
                    retryable=False,
                    stage=stage,
                )
            resolved[ref_id] = str(p)

        for ref_id, ref_b64 in request.references_b64.items():
            try:
                raw = base64.b64decode(ref_b64, validate=True)
            except Exception as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR,
                    message=f"Invalid base64 in references_b64[{ref_id!r}]: {exc}",
                    retryable=False,
                    stage=stage,
                ) from exc
            staged, _sr, _dur = decode_audio_bytes_to_file(
                raw, temp_dir, filename_hint=f"{ref_id}.flac", stage=stage
            )
            resolved[ref_id] = str(staged)

        default_raw = reference_audio_bytes
        if default_raw is None and request.reference_audio_b64:
            try:
                default_raw = base64.b64decode(request.reference_audio_b64, validate=True)
            except Exception as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR,
                    message=f"Invalid base64 reference_audio_b64: {exc}",
                    retryable=False,
                    stage=stage,
                ) from exc

        if default_raw is not None:
            staged_def, _sr, _dur = decode_audio_bytes_to_file(
                default_raw,
                temp_dir,
                filename_hint=request.reference_audio_filename or "reference.flac",
                stage=stage,
            )
            resolved["default"] = str(staged_def)
        elif request.reference_audio_path:
            ref_path = Path(request.reference_audio_path)
            if not ref_path.is_file():
                raise ComputeRemoteError(
                    code=ComputeErrorCode.INVALID_REQUEST,
                    message=f"reference_audio_path does not exist: {request.reference_audio_path}",
                    retryable=False,
                    stage=stage,
                )
            resolved["default"] = str(ref_path)

        return resolved

    def _finalize_tts_item_file(
        self,
        *,
        item: TtsSynthesizeItem,
        produced_file: Path,
        output_format: AudioFormat,
        include_audio_b64: bool,
    ) -> TtsBatchItemResult:
        encoded, sr, dur = encode_audio_file_bytes(
            produced_file, output_format, stage="tts_batch"
        )
        out_path_str: str | None = None
        if item.output_path and not include_audio_b64:
            materialize_audio_bytes_to_path(encoded, item.output_path, stage="tts_batch")
            out_path_str = str(item.output_path)

        return TtsBatchItemResult(
            item_id=item.item_id,
            ok=True,
            output_path=out_path_str,
            audio_b64=base64.b64encode(encoded).decode("ascii") if include_audio_b64 else None,
            output_format=output_format,
            sample_rate=sr,
            duration_seconds=dur,
        )

    def _run_callback_tts_item(
        self,
        *,
        fn: Callable[..., Any],
        item: TtsSynthesizeItem,
        request: TtsBatchRequest,
        resolved_refs: dict[str, str],
        temp_dir: Path,
        include_audio_b64: bool,
    ) -> TtsBatchItemResult:
        ref_key = item.reference_id or item.variant_value or "default"
        ref_path = resolved_refs.get(ref_key) or resolved_refs.get("default")
        staged_out = temp_dir / f"tts_{item.item_id}_{uuid.uuid4().hex[:8]}.wav"
        try:
            res = fn(
                item=item,
                request=request,
                reference_path=ref_path,
                output_path=str(staged_out),
            )
            if isinstance(res, tuple) and len(res) == 2:
                samples, sr = res
                sf.write(str(staged_out), np.asarray(samples, dtype="float32"), int(sr))
            elif isinstance(res, (str, Path)):
                staged_out = Path(res)
            return self._finalize_tts_item_file(
                item=item,
                produced_file=staged_out,
                output_format=request.output_format,
                include_audio_b64=include_audio_b64,
            )
        except Exception as exc:
            mapped = classify_compute_exception(exc, "tts_batch")
            return TtsBatchItemResult(
                item_id=item.item_id,
                ok=False,
                output_format=request.output_format,
                error=ComputeErrorPayload.model_validate(mapped.payload.model_dump()),
            )

    def _run_engine_tts_batch(
        self,
        *,
        lease_key: str,
        request: TtsBatchRequest,
        resolved_refs: dict[str, str],
        temp_dir: Path,
        include_audio_b64: bool,
    ) -> list[TtsBatchItemResult]:
        provider = request.provider_id
        batch_opts = dict(request.options)

        if provider == "voxcpm2":
            def _load_voxcpm2() -> Any:
                from src.core.engines.tts.voxcpm2 import VoxCPM2Engine
                from src.core.resources.model_reference import resolve_model_reference

                model_ref = resolve_model_reference(request.model) if request.model else None
                return VoxCPM2Engine(
                    model_dir=model_ref,
                    cfg_value=float(batch_opts.get("cfg_value", 2.0)),
                    inference_timesteps=int(batch_opts.get("inference_timesteps", 10)),
                    load_denoiser=False,
                    device_map=request.device,
                    reference_wav_path=(
                        resolved_refs.get("default") or next(iter(resolved_refs.values()), None)
                    ),
                )

            results: list[TtsBatchItemResult] = []
            with self.lease_manager.lease(lease_key, _load_voxcpm2, family="tts") as engine:
                for item in request.items:
                    staged_out = temp_dir / f"vox_{item.item_id}_{uuid.uuid4().hex[:8]}.wav"
                    try:
                        merged = {**batch_opts, **item.options}
                        engine.cfg_value = float(merged.get("cfg_value", engine.cfg_value))
                        engine.inference_timesteps = int(
                            merged.get("inference_timesteps", engine.inference_timesteps)
                        )
                        ref_key = item.reference_id or item.variant_value or "default"
                        engine.default_reference_wav = (
                            resolved_refs.get(ref_key) or resolved_refs.get("default")
                            if item.variant_kind == "reference" or ref_key in resolved_refs
                            else None
                        )
                        design_prefix = item.variant_value if item.variant_kind == "design" else ""
                        instruct = "，".join(p for p in (design_prefix, item.instruction) if p)
                        synth_text = f"({instruct}){item.text}" if instruct else item.text
                        engine.synthesize(synth_text, str(staged_out))
                        results.append(
                            self._finalize_tts_item_file(
                                item=item,
                                produced_file=staged_out,
                                output_format=request.output_format,
                                include_audio_b64=include_audio_b64,
                            )
                        )
                    except Exception as exc:
                        mapped = classify_compute_exception(exc, "tts_batch")
                        results.append(
                            TtsBatchItemResult(
                                item_id=item.item_id,
                                ok=False,
                                output_format=request.output_format,
                                error=mapped.payload,
                            )
                        )
            return results

        if provider == "qwen3":
            def _load_qwen3() -> _UnloadableHandle:
                import torch
                from qwen_tts import Qwen3TTSModel
                from src.core.resources.model_reference import resolve_model_reference

                device = request.device
                if device == "auto":
                    device = "cuda:0" if torch.cuda.is_available() else "cpu"
                dtype = {
                    "float32": torch.float32,
                    "float16": torch.float16,
                    "bfloat16": torch.bfloat16,
                }.get(
                    request.precision,
                    torch.float32 if device == "cpu" else torch.bfloat16,
                )
                model_path = (
                    resolve_model_reference(request.model)
                    if request.model
                    else "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
                )
                mdl = Qwen3TTSModel.from_pretrained(model_path, device_map=device, dtype=dtype)
                return _UnloadableHandle(mdl)

            results = []
            with self.lease_manager.lease(lease_key, _load_qwen3, family="tts") as handle:
                from src.core.tts import normalize_qwen3_language

                qwen_model = handle.target
                for item in request.items:
                    staged_out = temp_dir / f"qwen_{item.item_id}_{uuid.uuid4().hex[:8]}.wav"
                    try:
                        merged = {**batch_opts, **item.options}
                        gen_kwargs: dict[str, Any] = {
                            "text": item.text,
                            "language": normalize_qwen3_language(item.language),
                            "temperature": float(merged.get("temperature", 0.7)),
                            "top_p": float(merged.get("top_p", 0.8)),
                        }
                        for opt_key in ("do_sample", "top_k", "repetition_penalty", "max_new_tokens"):
                            if opt_key in merged:
                                gen_kwargs[opt_key] = merged[opt_key]

                        ref_key = item.reference_id or item.variant_value or "default"
                        ref_audio = resolved_refs.get(ref_key) or resolved_refs.get("default")
                        if item.variant_kind == "reference" or (
                            item.variant_kind == "default" and ref_audio is not None
                        ):
                            if not ref_audio:
                                raise ValueError("Voice clone requires reference audio")
                            xvec_only = bool(merged.get("x_vector_only_mode", False))
                            wavs, rate = qwen_model.generate_voice_clone(
                                **gen_kwargs,
                                ref_audio=ref_audio,
                                ref_text=None if xvec_only else (item.reference_transcript or None),
                                x_vector_only_mode=xvec_only,
                            )
                        elif item.variant_kind == "design":
                            instruct = "，".join(
                                x for x in (item.variant_value, item.instruction) if x
                            )
                            wavs, rate = qwen_model.generate_voice_design(
                                **gen_kwargs, instruct=instruct
                            )
                        else:
                            speaker = item.speaker or item.variant_value or "Chelsie"
                            wavs, rate = qwen_model.generate_custom_voice(
                                **gen_kwargs, speaker=speaker, instruct=item.instruction
                            )
                        sf.write(str(staged_out), wavs[0], rate)
                        results.append(
                            self._finalize_tts_item_file(
                                item=item,
                                produced_file=staged_out,
                                output_format=request.output_format,
                                include_audio_b64=include_audio_b64,
                            )
                        )
                    except Exception as exc:
                        mapped = classify_compute_exception(exc, "tts_batch")
                        results.append(
                            TtsBatchItemResult(
                                item_id=item.item_id,
                                ok=False,
                                output_format=request.output_format,
                                error=mapped.payload,
                            )
                        )
            return results

        raise ComputeRemoteError(
            code=ComputeErrorCode.MODEL_NOT_AVAILABLE,
            message=f"Unsupported local TTS provider: {provider!r}",
            retryable=False,
            stage="tts_batch",
        )
