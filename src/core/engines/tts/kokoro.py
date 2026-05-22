"""Kokoro TTS provider wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class KokoroTtsEngine:
    """Thin adapter around the official kokoro KPipeline interface."""

    VOICE_LANG_PREFIXES = {
        "af_": "a",
        "am_": "a",
        "bf_": "b",
        "bm_": "b",
        "zf_": "z",
        "zm_": "z",
    }

    def __init__(
        self,
        *,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str | None = None,
        repo_id: str | None = None,
        split_pattern: str = r"\n+",
        sample_rate: int = 24000,
    ) -> None:
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError(
                "Kokoro TTS requires the optional 'kokoro' dependency. "
                "Install it with `pip install kokoro soundfile` and make sure espeak-ng is installed."
            ) from exc

        self.voice = voice or "af_heart"
        self.speed = float(speed)
        self.lang_code = lang_code or self._infer_lang_code(self.voice)
        self.repo_id = repo_id
        self.split_pattern = split_pattern
        self.sample_rate = int(sample_rate)

        pipeline_kwargs = {"lang_code": self.lang_code}
        if self.repo_id:
            pipeline_kwargs["repo_id"] = self.repo_id

        try:
            self.pipeline = KPipeline(**pipeline_kwargs)
        except TypeError:
            pipeline_kwargs.pop("repo_id", None)
            self.pipeline = KPipeline(**pipeline_kwargs)
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Kokoro pipeline: {exc}") from exc

    def synthesize(self, text: str, output_path: str) -> str:
        import numpy as np
        import soundfile as sf

        generator = self.pipeline(
            text,
            voice=self.voice,
            speed=self.speed,
            split_pattern=self.split_pattern,
        )
        chunks: list[Any] = []
        for item in generator:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            chunks.append(item[2])

        if not chunks:
            raise RuntimeError("Kokoro returned no audio chunks")

        audio = np.concatenate([np.asarray(chunk, dtype="float32") for chunk in chunks], axis=0)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), audio, self.sample_rate)
        return str(target)

    def unload(self) -> None:
        if hasattr(self, "pipeline"):
            del self.pipeline
            self.pipeline = None

    @classmethod
    def _infer_lang_code(cls, voice: str) -> str:
        for prefix, lang_code in cls.VOICE_LANG_PREFIXES.items():
            if voice.startswith(prefix):
                return lang_code
        return "a"
