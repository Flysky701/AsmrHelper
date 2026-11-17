"""Optional Transformers adapter for litagin/anime-whisper (not CTranslate2)."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any


class AnimeWhisperRecognizer:
    """Return native Whisper segment timestamps, without inventing alignment."""

    def __init__(
        self,
        *,
        model_size: str,
        language: str = "ja",
        device: str = "auto",
        batch_size: int = 1,
        no_repeat_ngram_size: int = 0,
        repetition_penalty: float = 1.0,
    ) -> None:
        if language != "ja":
            raise ValueError("Anime Whisper currently supports Japanese (ja) only")
        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise RuntimeError(
                "Anime Whisper requires its optional Transformers runtime. "
                "Open 引擎与资源 and repair dependencies for anime-whisper."
            ) from exc

        self._device = (
            ("cuda:0" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        )
        self._generate_kwargs = {
            "language": "ja",
            "task": "transcribe",
            "condition_on_prev_tokens": False,
            "no_repeat_ngram_size": no_repeat_ngram_size,
            "repetition_penalty": repetition_penalty,
        }
        # The author warns against initial_prompt. Do not pass prompt_ids or
        # reuse Faster-Whisper decoding options. Word alignment_heads in the
        # upstream config reference layers absent from this two-layer decoder;
        # return_timestamps=True requests segment tokens, never word alignment.
        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=model_size,
            device=self._device,
            dtype=torch.float16 if self._device.startswith("cuda") else torch.float32,
            # Keep Whisper's native long-form path. Pipeline overlap chunking
            # lost a repeated utterance in the real 35-second regression sample
            # when this model omitted closing timestamp tokens.
            batch_size=batch_size,
            trust_remote_code=False,
        )

    def recognize(self, audio_path: str, output_path: str | None = None) -> list[dict[str, Any]]:
        audio = self._read_audio(audio_path)
        if not len(audio):
            raise ValueError("Anime Whisper input contains no audio samples")
        result = self._pipe(
            {"raw": audio, "sampling_rate": 16000},
            return_timestamps=True,
            generate_kwargs=dict(self._generate_kwargs),
        )
        segments = self._normalize_segments(result, duration_seconds=len(audio) / 16000)
        if output_path:
            from src.core.subtitles import SubtitleDocument, SubtitleExporter, SubtitleSegment

            # The existing ASR runtime labels output as SRT; write actual SRT.
            SubtitleExporter().export_document(
                SubtitleDocument(
                    segments=[
                        SubtitleSegment(
                            start=item["start"],
                            end=item["end"],
                            text=item["text"],
                            language="ja",
                            recognition_metadata={"timestamp_source": item["timestamp_source"]},
                        )
                        for item in segments
                    ],
                    language="ja",
                ),
                output_path=output_path,
                fmt="srt",
            )
        return segments

    @staticmethod
    def _read_audio(audio_path: str):
        import numpy as np

        from src.utils import get_ffmpeg

        # Use the project's bundled decoder, not Transformers' bare `ffmpeg`
        # executable lookup. Supplying 16 kHz PCM also avoids torchaudio resampling.
        decoded = subprocess.run(
            [
                get_ffmpeg(),
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(Path(audio_path).resolve()),
                "-f",
                "f32le",
                "-acodec",
                "pcm_f32le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if decoded.returncode:
            detail = decoded.stderr.decode("utf-8", errors="replace")[-1000:]
            raise ValueError(f"Anime Whisper could not decode audio: {detail}")
        return np.frombuffer(decoded.stdout, dtype="<f4").copy()

    @staticmethod
    def _normalize_segments(
        result: dict[str, Any], *, duration_seconds: float
    ) -> list[dict[str, Any]]:
        segments = []
        chunks = [
            chunk for chunk in result.get("chunks") or [] if str(chunk.get("text") or "").strip()
        ]
        for index, chunk in enumerate(chunks):
            text = str(chunk.get("text") or "").strip()
            timestamp_source = "whisper_segment"
            try:
                start, end = chunk["timestamp"]
                # Transformers can return an open final cue when the recording
                # ends before Whisper emits a closing timestamp. Keep its native
                # start; close only this last cue at the measured audio boundary
                # and expose that distinction to downstream consumers. Missing
                # starts and missing ends in the middle still fail explicitly.
                if end is None and index == len(chunks) - 1:
                    end = duration_seconds
                    timestamp_source = "whisper_segment_audio_end"
                start, end = float(start), float(end)
                if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
                    raise ValueError("invalid timestamp range")
                # Decoder padding can extend the final cue beyond the audio.
                end = min(end, duration_seconds)
                if end <= start:
                    raise ValueError("timestamp is outside the audio")
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Anime Whisper did not return valid segment timestamps; "
                    "no whole-audio subtitle fallback was written"
                ) from exc
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "timestamp_source": timestamp_source,
                }
            )
        if str(result.get("text") or "").strip() and not segments:
            raise RuntimeError("Anime Whisper returned text without segment timestamps")
        return segments

    def unload(self) -> None:
        self._pipe = None
        import torch

        if self._device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
