"""Core pipeline orchestration services."""

from __future__ import annotations

from typing import Any, Callable

from .models import PipelineExecutionContext


LANG_MAP = {
    "ja": ("日文", "中文"),
    "zh": ("中文", "英文"),
    "en": ("英文", "中文"),
}


class LegacyPipelineOrchestrator:
    """Build legacy pipeline config objects from task-driven execution context."""

    def __init__(
        self,
        *,
        pipeline_loader: Callable[[], tuple[type, type]] | None = None,
    ) -> None:
        self._pipeline_loader = pipeline_loader or self._load_pipeline_runtime

    def run(
        self,
        context: PipelineExecutionContext,
        *,
        progress_callback: Callable[[str], None] | None = None,
        preset: str = "asmr_bilingual",
    ) -> dict[str, Any]:
        pipeline_class, _ = self._pipeline_loader()
        config = self.build_legacy_config(context)
        return pipeline_class(config).run(
            preset=preset,
            progress_callback=progress_callback,
        )

    def build_legacy_config(self, context: PipelineExecutionContext):
        _, pipeline_config_class = self._pipeline_loader()
        stage_profiles = dict(context.execution_profile.get("stages", {}))
        mix_options = dict(context.execution_profile.get("mix", {}))
        pipeline_options = dict(context.execution_profile.get("pipeline", {}))

        source_lang = pipeline_options.get("source_lang", context.source_lang)
        target_lang = pipeline_options.get("target_lang", context.target_lang)
        source_label, _ = LANG_MAP[source_lang]
        target_label = LANG_MAP[target_lang][0]

        tts_profile = dict(stage_profiles.get("tts", {}))
        asr_profile = dict(stage_profiles.get("asr", {}))
        llm_profile = dict(stage_profiles.get("llm", {}))
        separator_profile = dict(stage_profiles.get("separator", {}))

        return pipeline_config_class(
            input_path=context.input_path,
            output_dir=context.output_dir,
            vtt_path=context.companion_subtitle_path,
            use_vocal_separator=bool(pipeline_options.get("use_vocal_separator", True)),
            vocal_model=separator_profile.get("model", pipeline_options.get("vocal_model", "htdemucs")),
            asr_model=asr_profile.get("model", pipeline_options.get("asr_model", "base")),
            asr_language=source_lang,
            use_translate=True,
            translate_provider=llm_profile.get("provider", pipeline_options.get("translate_provider", "deepseek")),
            source_lang=source_label,
            target_lang=target_label,
            use_tts=True,
            tts_engine=tts_profile.get("provider", pipeline_options.get("tts_engine", "edge")),
            tts_voice=tts_profile.get("common_options", {}).get(
                "voice", pipeline_options.get("tts_voice", "zh-CN-XiaoxiaoNeural")
            ),
            qwen3_voice=tts_profile.get("common_options", {}).get(
                "voice", pipeline_options.get("tts_voice", "zh-CN-XiaoxiaoNeural")
            ),
            voice_profile_id=tts_profile.get("provider_options", {}).get(
                "voice_profile_id", pipeline_options.get("voice_profile_id")
            ),
            tts_speed=float(
                tts_profile.get("common_options", {}).get(
                    "speed", pipeline_options.get("tts_speed", 1.0)
                )
            ),
            use_mixer=True,
            original_volume=float(
                mix_options.get("original_volume", pipeline_options.get("original_volume", 0.85))
            ),
            tts_volume_ratio=float(
                mix_options.get("tts_volume_ratio", pipeline_options.get("tts_volume_ratio", 0.5))
            ),
            tts_delay_ms=float(
                mix_options.get("tts_delay", pipeline_options.get("tts_delay", 0.0))
            ),
            skip_existing=bool(pipeline_options.get("skip_existing", False)),
            output_mode=str(pipeline_options.get("output_mode", "single")),
            batch_root_dir=str(pipeline_options.get("batch_root_dir", "")),
        )

    @staticmethod
    def _load_pipeline_runtime() -> tuple[type, type]:
        from src.core import Pipeline as core_pipeline
        from src.core import PipelineConfig as core_pipeline_config

        return core_pipeline, core_pipeline_config
