"""Application-layer facade for audio utility operations."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

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

logger = logging.getLogger(__name__)

_LANG_MAP = {
    "ja": "日文",
    "zh": "中文",
    "en": "英文",
}


class AudioToolService:
    """Stable application-facing facade for audio utility operations."""

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
            self._write_bilingual_subtitle(segments, output_path, request.bilingual)
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

    # --- Internal helpers ---

    @staticmethod
    def _write_bilingual_subtitle(
        segments: list[dict],
        output_path: str,
        bilingual: bool,
    ) -> None:
        ext = Path(output_path).suffix.lower()
        if ext == ".vtt":
            AudioToolService._write_bilingual_vtt(segments, output_path, bilingual)
        elif ext == ".srt":
            AudioToolService._write_bilingual_srt(segments, output_path, bilingual)
        else:
            AudioToolService._write_bilingual_srt(segments, output_path, bilingual)

    @staticmethod
    def _format_vtt_timestamp(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        total_ms = int(round(seconds * 1000))
        h, remainder = divmod(total_ms, 3_600_000)
        m, remainder = divmod(remainder, 60_000)
        s, ms = divmod(remainder, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _write_bilingual_vtt(
        segments: list[dict],
        output_path: str,
        bilingual: bool,
    ) -> None:
        lines = ["WEBVTT", ""]
        for seg in segments:
            start = AudioToolService._format_vtt_timestamp(seg["start"])
            end = AudioToolService._format_vtt_timestamp(seg["end"])
            lines.append(f"{start} --> {end}")
            lines.append(seg["text"])
            if bilingual and seg.get("translation"):
                lines.append(seg["translation"])
            lines.append("")

        Path(output_path).write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _write_bilingual_srt(
        segments: list[dict],
        output_path: str,
        bilingual: bool,
    ) -> None:
        blocks = []
        for i, seg in enumerate(segments, start=1):
            start = AudioToolService._format_srt_timestamp(seg["start"])
            end = AudioToolService._format_srt_timestamp(seg["end"])
            text = seg["text"]
            if bilingual and seg.get("translation"):
                text = f"{text}\n{seg['translation']}"
            blocks.append(f"{i}\n{start} --> {end}\n{text}")

        Path(output_path).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


_service: AudioToolService | None = None
_lock = threading.Lock()


def get_audio_tool_service() -> AudioToolService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = AudioToolService()
    return _service
