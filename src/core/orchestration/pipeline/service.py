"""Core pipeline orchestration services."""

from __future__ import annotations

from typing import Any, Callable

from .executor import PipelineExecutor
from .models import (
    MixConfig,
    PipelineExecutionContext,
    PipelineExecutionPlan,
    StageBinding,
    StageKind,
)
from .planner import LANG_MAP, build_execution_plan
from .result_mapper import ArtifactResultMapper


class LegacyPipelineOrchestrator:
    """Orchestrator that delegates to PipelineExecutor by default.

    This class now serves as a compatibility wrapper. The default `run()`
    method uses the new PipelineExecutor. The legacy path (via PipelineConfig
    and the old Pipeline class) is available through `run_legacy()`.
    """

    def __init__(
        self,
        *,
        executor: PipelineExecutor | None = None,
        pipeline_loader: Callable[[], tuple[type, type]] | None = None,
    ) -> None:
        self._executor = executor or PipelineExecutor()
        self._pipeline_loader = pipeline_loader or self._load_pipeline_runtime

    def run(
        self,
        context: PipelineExecutionContext,
        *,
        progress_callback: Callable[[str], None] | None = None,
        preset: str = "asmr_bilingual",
    ) -> dict[str, Any]:
        """Run the pipeline using the new PipelineExecutor.

        Builds a PipelineExecutionPlan and executes via the new executor
        that drives engine runtimes directly.
        """
        plan = build_execution_plan(context)
        return self._executor.execute(plan, progress_callback=progress_callback)

    def run_legacy(
        self,
        context: PipelineExecutionContext,
        *,
        progress_callback: Callable[[str], None] | None = None,
        preset: str = "asmr_bilingual",
    ) -> dict[str, Any]:
        """Run the pipeline using the legacy Pipeline class path.

        This is the explicit backward-compatibility path for callers that
        need the old PipelineConfig-based execution.
        """
        plan = build_execution_plan(context)
        return self._execute_plan_legacy(plan, progress_callback=progress_callback, preset=preset)

    def build_plan(self, context: PipelineExecutionContext) -> PipelineExecutionPlan:
        """Build an execution plan without running it.

        Useful for inspection, validation, or preview before execution.
        """
        return build_execution_plan(context)

    def _execute_plan_legacy(
        self,
        plan: PipelineExecutionPlan,
        *,
        progress_callback: Callable[[str], None] | None = None,
        preset: str = "asmr_bilingual",
    ) -> dict[str, Any]:
        """Execute a plan via the legacy pipeline adapter."""
        pipeline_class, _ = self._pipeline_loader()
        config = self._plan_to_legacy_config(plan)
        raw_results = pipeline_class(config).run(
            preset=preset,
            progress_callback=progress_callback,
        )
        return ArtifactResultMapper.normalize_results(raw_results)

    def _plan_to_legacy_config(self, plan: PipelineExecutionPlan):
        """Convert a PipelineExecutionPlan to a legacy PipelineConfig.

        This is the backward-compatibility adapter. New code should
        work with PipelineExecutionPlan; this method exists only to
        bridge to the legacy Pipeline class.
        """
        _, pipeline_config_class = self._pipeline_loader()

        return pipeline_config_class(
            # I/O
            input_path=plan.input_path,
            output_dir=plan.output_dir,
            vtt_path=plan.companion_subtitle_path,
            # Separation
            use_vocal_separator=plan.separation.enabled,
            vocal_model=plan.separation.model,
            # ASR
            use_asr=plan.asr.enabled,
            asr_model=plan.asr.model,
            asr_language=plan.source_lang,
            # Translation
            use_translate=plan.translation.enabled,
            translate_provider=plan.translation.provider,
            source_lang=plan.source_label,
            target_lang=plan.target_label,
            # TTS
            use_tts=plan.tts.enabled,
            tts_engine=plan.tts.provider,
            tts_voice=plan.tts.common_options.get("voice", "zh-CN-XiaoxiaoNeural"),
            qwen3_voice=plan.tts.common_options.get("voice", "zh-CN-XiaoxiaoNeural"),
            voice_profile_id=plan.tts.provider_options.get("voice_profile_id"),
            tts_speed=plan.tts.common_options.get("speed", 1.0),
            # Mix
            use_mixer=plan.mix.enabled,
            original_volume=plan.mix.original_volume,
            tts_volume_ratio=plan.mix.tts_volume_ratio,
            tts_delay_ms=plan.mix.tts_delay_ms,
            # Pipeline behavior
            skip_existing=plan.skip_existing,
            output_mode=plan.output_mode,
            batch_root_dir=plan.batch_root_dir,
            pipeline_mode="custom",
            forced_active_steps=plan.legacy_active_steps,
            # Subtitle
            clean_subtitle=plan.subtitle.clean_enabled,
            clean_sound_effects=plan.subtitle.clean_sound_effects,
            clean_speaker_names=plan.subtitle.clean_speaker_names,
            export_subtitle_format=plan.subtitle.export_format,
        )

    # --- Legacy compatibility ---

    def build_legacy_config(self, context: PipelineExecutionContext):
        """Legacy adapter: build a PipelineConfig from context.

        Deprecated: use build_plan() instead.
        Kept for backward compatibility with any direct callers.
        """
        plan = build_execution_plan(context)
        return self._plan_to_legacy_config(plan)

    @staticmethod
    def _load_pipeline_runtime() -> tuple[type, type]:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.core import Pipeline as core_pipeline
            from src.core import PipelineConfig as core_pipeline_config

        return core_pipeline, core_pipeline_config
