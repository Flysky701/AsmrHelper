"""Qwen3-ASR provider wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class Qwen3AsrRecognizer:
    """Adapt Qwen3-ASR transcription results to the app's segment contract."""

    LANGUAGE_HINTS = {
        "auto": None,
        "zh": "Chinese",
        "en": "English",
        "ja": "Japanese",
        "yue": "Cantonese",
        "ko": "Korean",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "pt": "Portuguese",
        "ru": "Russian",
        "th": "Thai",
        "vi": "Vietnamese",
        "id": "Indonesian",
        "it": "Italian",
        "ar": "Arabic",
        "hi": "Hindi",
        "ms": "Malay",
        "nl": "Dutch",
    }

    DTYPE_MAP = {
        "float16": "float16",
        "fp16": "float16",
        "bfloat16": "bfloat16",
        "bf16": "bfloat16",
        "float32": "float32",
        "fp32": "float32",
    }

    def __init__(
        self,
        *,
        model_size: str,
        language: str | None = None,
        device_map: str | None = None,
        dtype: str | None = None,
        attn_implementation: str | None = None,
        max_inference_batch_size: int = 1,
        max_new_tokens: int = 512,
        forced_aligner: str | None = None,
        forced_aligner_kwargs: dict[str, Any] | None = None,
        return_time_stamps: bool = False,
        context: str = "",
    ) -> None:
        try:
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise RuntimeError(
                "Qwen3-ASR requires the optional 'qwen-asr' dependency. "
                "Install it with `uv sync --extra qwen_asr` or `pip install qwen-asr`."
            ) from exc

        self._language = self.LANGUAGE_HINTS.get(language or "", language)
        self._return_time_stamps = bool(return_time_stamps or forced_aligner)
        self._context = context

        model_kwargs: dict[str, Any] = {
            "max_inference_batch_size": max_inference_batch_size,
            "max_new_tokens": max_new_tokens,
        }
        resolved_device_map = device_map or self._default_device_map()
        if resolved_device_map:
            model_kwargs["device_map"] = resolved_device_map
        resolved_dtype = self._resolve_dtype(dtype)
        if resolved_dtype is not None:
            model_kwargs["dtype"] = resolved_dtype
        if attn_implementation:
            model_kwargs["attn_implementation"] = attn_implementation
        if forced_aligner:
            model_kwargs["forced_aligner"] = forced_aligner
        if forced_aligner_kwargs:
            model_kwargs["forced_aligner_kwargs"] = forced_aligner_kwargs

        try:
            self.model = Qwen3ASRModel.from_pretrained(model_size, **model_kwargs)
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Qwen3-ASR model '{model_size}': {exc}") from exc

    def recognize(self, audio_path: str, output_path: str | None = None) -> list[dict[str, Any]]:
        source = Path(audio_path)
        results = self.model.transcribe(
            audio=str(source),
            context=self._context,
            language=self._language,
            return_time_stamps=self._return_time_stamps,
        )
        duration = self._read_duration_seconds(source)
        segments = self._normalize_segments(results, duration_seconds=duration)
        if output_path:
            self._save_results(segments, output_path)
        return segments

    def unload(self) -> None:
        if hasattr(self, "model"):
            del self.model
            self.model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            return

    @classmethod
    def _normalize_segments(cls, raw_results: Any, *, duration_seconds: float) -> list[dict[str, Any]]:
        if isinstance(raw_results, list):
            items = raw_results
        elif raw_results is None:
            items = []
        else:
            items = [raw_results]

        segments: list[dict[str, Any]] = []
        texts: list[str] = []
        for item in items:
            if item is None:
                continue
            time_stamps = cls._get_value(item, "time_stamps")
            if isinstance(time_stamps, list) and time_stamps:
                for stamp in time_stamps:
                    normalized = cls._normalize_timestamp_item(stamp)
                    if normalized:
                        segments.append(normalized)

            text = str(cls._get_value(item, "text") or "").strip()
            if text:
                texts.append(text)

        if segments:
            return segments

        combined = "\n".join(text for text in texts if text)
        if not combined:
            return []
        return [{"start": 0.0, "end": max(duration_seconds, 0.0), "text": combined}]

    @classmethod
    def _normalize_timestamp_item(cls, item: Any) -> dict[str, Any] | None:
        text = str(cls._get_value(item, "text") or cls._get_value(item, "token") or "").strip()
        if not text:
            return None
        start = cls._coerce_seconds(
            cls._get_value(item, "start")
            or cls._get_value(item, "start_time")
            or cls._sequence_value(item, 1)
            or cls._sequence_value(item, 0)
        )
        end = cls._coerce_seconds(
            cls._get_value(item, "end")
            or cls._get_value(item, "end_time")
            or cls._sequence_value(item, 2)
            or cls._sequence_value(item, 1)
        )
        if end <= start:
            end = start
        return {"start": start, "end": end, "text": text}

    @staticmethod
    def _get_value(item: Any, name: str) -> Any:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    @staticmethod
    def _sequence_value(item: Any, index: int) -> Any:
        if isinstance(item, (list, tuple)) and len(item) > index:
            return item[index]
        return None

    @staticmethod
    def _coerce_seconds(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        if isinstance(value, int):
            return float(value) / 1000.0
        if isinstance(value, str) and value.isdigit():
            return float(int(value)) / 1000.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1000:
            return numeric / 1000.0
        return numeric

    @staticmethod
    def _default_device_map() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda:0"
        except ImportError:
            pass
        return "cpu"

    @classmethod
    def _resolve_dtype(cls, dtype_name: str | None):
        if not dtype_name:
            return None
        normalized = cls.DTYPE_MAP.get(str(dtype_name).lower())
        if not normalized:
            return None
        try:
            import torch

            return getattr(torch, normalized)
        except (ImportError, AttributeError):
            return None

    @staticmethod
    def _read_duration_seconds(audio_path: Path) -> float:
        try:
            import soundfile as sf

            info = sf.info(str(audio_path))
            if info.samplerate and info.frames:
                return float(info.frames) / float(info.samplerate)
        except Exception:
            return 0.0
        return 0.0

    @staticmethod
    def _save_results(results: list[dict[str, Any]], output_path: str) -> None:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as handle:
            for index, item in enumerate(results, start=1):
                handle.write(f"[{index}] {item['start']:.3f}s - {item['end']:.3f}s\n")
                handle.write(f"{item['text']}\n\n")
