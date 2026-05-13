"""Application-layer facade for the audio pipeline."""

from __future__ import annotations

import threading

from src.core import Pipeline, PipelineConfig

from ..dto import PipelineRequest, PipelineResult
from ..errors import AppExecutionError, AppValidationError


LANG_MAP = {
    "ja": ("日文", "中文"),
    "zh": ("中文", "英文"),
    "en": ("英文", "中文"),
}


class PipelineService:
    """Wrap core pipeline invocation behind stable request/result DTOs."""

    def run_audio_pipeline(self, request: PipelineRequest) -> PipelineResult:
        if not request.input_path:
            raise AppValidationError("input_path is required")

        source_label, target_label = LANG_MAP.get(request.source_lang, ("日文", "中文"))
        if request.target_lang == "zh":
            target_label = "中文"
        elif request.target_lang == "en":
            target_label = "英文"
        elif request.target_lang == "ja":
            target_label = "日文"

        config = PipelineConfig(
            input_path=request.input_path,
            output_dir=request.output_dir,
            use_vocal_separator=True,
            vocal_model=request.vocal_model,
            asr_model=request.asr_model,
            asr_language=request.source_lang,
            use_translate=True,
            translate_provider=request.translate_provider,
            source_lang=source_label,
            target_lang=target_label,
            use_tts=True,
            tts_engine=request.tts_engine,
            tts_voice=request.tts_voice,
            use_mixer=True,
            tts_delay_ms=request.tts_delay,
            skip_existing=request.skip_existing,
        )

        try:
            results = Pipeline(config).run(preset="asmr_bilingual")
        except AppValidationError:
            raise
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return PipelineResult(
            success=True,
            input_path=results.get("input", request.input_path),
            mix_path=results.get("mix_path"),
            exported_subtitle=results.get("exported_subtitle"),
            steps=results.get("steps", {}),
            total_duration=float(results.get("total_duration", 0.0)),
            error_message=results.get("error"),
        )


_service: PipelineService | None = None
_lock = threading.Lock()


def get_pipeline_service() -> PipelineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PipelineService()
    return _service
