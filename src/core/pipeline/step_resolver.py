"""Step resolution logic for pipeline modes."""

from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from . import PipelineConfig


class StepResolver:
    """Resolve active execution steps based on mode and subtitle state."""

    def __init__(self, config: "PipelineConfig"):
        self.config = config

    def resolve_active_steps(self, has_subtitle: bool, is_chinese_subtitle: bool) -> List[str]:
        config = self.config
        mode = config.pipeline_mode

        if mode == "full":
            return ["vocal_separator", "asr", "translate", "tts", "mixer"]

        if mode == "asr_only":
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            return steps

        if mode == "subtitle_only":
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            if config.use_translate and not is_chinese_subtitle:
                steps.append("translate")
            return steps

        if mode == "tts_only":
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            steps.extend(["asr", "translate", "tts"])
            return steps

        if mode == "custom":
            steps = []
            if config.use_vocal_separator:
                steps.append("vocal_separator")
            if config.use_asr:
                steps.append("asr")
            if config.use_translate:
                steps.append("translate")
            if config.use_tts:
                steps.append("tts")
            if config.use_mixer:
                steps.append("mixer")
            return steps

        return ["vocal_separator", "asr", "translate", "tts", "mixer"]
