"""Fun-ASR provider wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FunAsrRecognizer:
    """Adapt Fun-ASR/FunASR inference results to the app's segment contract."""

    LANGUAGE_HINTS = {
        "auto": None,
        "zh": "Chinese",
        "en": "English",
        "ja": "Japanese",
    }

    def __init__(
        self,
        *,
        model_size: str,
        language: str | None = None,
        device: str = "auto",
        hub: str = "hf",
        batch_size: int = 1,
        sentence_timestamp: bool = True,
        trust_remote_code: bool = True,
        remote_code_path: str | None = None,
        hotwords: list[str] | str | None = None,
        vad_model: str | None = None,
        vad_kwargs: dict[str, Any] | None = None,
    ) -> None:
        try:
            from funasr import AutoModel
        except ModuleNotFoundError as exc:
            missing_module = str(exc.name or "unknown")
            if missing_module == "funasr":
                message = (
                    "Fun-ASR requires the optional 'funasr' dependency. "
                    "Open 引擎与资源 and choose 修复依赖 for the selected Fun-ASR model."
                )
            else:
                message = (
                    f"Fun-ASR runtime dependency '{missing_module}' is missing. "
                    "Open 引擎与资源 and choose 修复依赖 for the selected Fun-ASR model."
                )
            raise RuntimeError(message) from exc
        except ImportError as exc:
            raise RuntimeError(f"Fun-ASR runtime dependencies could not be imported: {exc}") from exc

        self._device = self._resolve_device(device)
        self._language = self.LANGUAGE_HINTS.get(language or "", language)
        self._batch_size = batch_size
        self._sentence_timestamp = sentence_timestamp
        self._hotwords = hotwords

        model_kwargs: dict[str, Any] = {
            "model": model_size,
            "device": self._device,
            "hub": hub,
        }
        if trust_remote_code:
            model_kwargs["trust_remote_code"] = True
        remote_code = self._resolve_remote_code(remote_code_path)
        if remote_code:
            model_kwargs["remote_code"] = remote_code
        if vad_model:
            model_kwargs["vad_model"] = vad_model
        if vad_kwargs:
            model_kwargs["vad_kwargs"] = vad_kwargs

        try:
            self.model = AutoModel(**model_kwargs)
        except Exception as exc:
            hint = (
                " If the installed funasr package cannot resolve Fun-ASR directly, set "
                "`provider_options.remote_code_path` to a local clone of "
                "https://github.com/FunAudioLLM/Fun-ASR (pointing at its model.py)."
            )
            raise RuntimeError(f"failed to initialize Fun-ASR model '{model_size}': {exc}.{hint}") from exc

    def recognize(self, audio_path: str, output_path: str | None = None) -> list[dict[str, Any]]:
        source = Path(audio_path)
        result = self.model.generate(
            input=str(source),
            batch_size=self._batch_size,
            sentence_timestamp=self._sentence_timestamp,
            **self._build_generate_kwargs(),
        )
        duration = self._read_duration_seconds(source)
        segments = self._normalize_segments(result, duration_seconds=duration)

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

    def _build_generate_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self._language:
            kwargs["language"] = self._language
        if self._hotwords:
            kwargs["hotwords"] = self._hotwords
        return kwargs

    @classmethod
    def _normalize_segments(cls, raw_result: Any, *, duration_seconds: float) -> list[dict[str, Any]]:
        payload = raw_result[0] if isinstance(raw_result, tuple) and raw_result else raw_result
        if isinstance(payload, dict):
            items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        segments: list[dict[str, Any]] = []
        loose_texts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            sentence_info = item.get("sentence_info")
            if isinstance(sentence_info, list):
                for sentence in sentence_info:
                    normalized = cls._normalize_sentence(sentence)
                    if normalized:
                        segments.append(normalized)

            normalized_item = cls._normalize_sentence(item)
            if normalized_item and not sentence_info:
                if normalized_item["start"] == 0.0 and normalized_item["end"] == 0.0 and duration_seconds > 0:
                    normalized_item["end"] = duration_seconds
                segments.append(normalized_item)

            text = str(item.get("text", "")).strip()
            if text:
                loose_texts.append(text)

        if segments:
            return segments

        combined = "\n".join(text for text in loose_texts if text)
        if not combined:
            return []
        return [{"start": 0.0, "end": max(duration_seconds, 0.0), "text": combined}]

    @classmethod
    def _normalize_sentence(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        text = str(item.get("text", "")).strip()
        if not text:
            return None

        start = cls._coerce_seconds(item.get("start"))
        end = cls._coerce_seconds(item.get("end"))
        if end <= start:
            start_from_ts, end_from_ts = cls._bounds_from_timestamps(item.get("timestamp") or item.get("timestamps"))
            if start == 0.0 and end == 0.0:
                start = start_from_ts
            end = max(end, end_from_ts)

        if end <= start:
            end = start

        return {"start": start, "end": end, "text": text}

    @staticmethod
    def _bounds_from_timestamps(value: Any) -> tuple[float, float]:
        if not isinstance(value, list) or not value:
            return 0.0, 0.0

        first = value[0]
        last = value[-1]
        start = FunAsrRecognizer._extract_time(first, "start")
        end = FunAsrRecognizer._extract_time(last, "end")
        return start, max(start, end)

    @staticmethod
    def _extract_time(value: Any, edge: str) -> float:
        if isinstance(value, dict):
            if edge == "start":
                return FunAsrRecognizer._coerce_seconds(value.get("start") or value.get("start_time"))
            return FunAsrRecognizer._coerce_seconds(value.get("end") or value.get("end_time"))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            index = 0 if edge == "start" else 1
            return FunAsrRecognizer._coerce_seconds(value[index])
        return 0.0

    @staticmethod
    def _coerce_seconds(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1000:
            return numeric / 1000.0
        return numeric

    @staticmethod
    def _resolve_remote_code(remote_code_path: str | None) -> str | None:
        if not remote_code_path:
            return None
        candidate = Path(remote_code_path)
        if candidate.is_dir():
            candidate = candidate / "model.py"
        if candidate.exists():
            return str(candidate.resolve())
        return None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda:0"
        except ImportError:
            pass
        return "cpu"

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
