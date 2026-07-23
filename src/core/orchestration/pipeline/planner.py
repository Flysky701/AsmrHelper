"""Stage planner — builds a PipelineExecutionPlan from execution context."""

from __future__ import annotations

from typing import Any

from .models import (
    MixConfig,
    PipelineExecutionContext,
    PipelineExecutionPlan,
    PipelineMode,
    StageBinding,
    StageKind,
    SubtitleConfig,
)

LANG_MAP = {
    "ja": ("日文", "中文"),
    "zh": ("中文", "英文"),
    "en": ("英文", "中文"),
}


def _resolve_lang_labels(source_lang: str, target_lang: str) -> tuple[str, str]:
    source_label = LANG_MAP.get(source_lang, (source_lang, ""))[0]
    target_entry = LANG_MAP.get(target_lang)
    target_label = target_entry[0] if target_entry else target_lang
    return source_label, target_label


def _resolve_stage_flags(mode: PipelineMode, pipeline_opts: dict[str, Any]) -> dict[str, bool]:
    if mode == PipelineMode.ASR_ONLY:
        return {
            "separation": bool(pipeline_opts.get("use_vocal_separator", True)),
            "asr": True,
            "translation": False,
            "tts": False,
            "mix": False,
        }
    if mode == PipelineMode.SUBTITLE_ONLY:
        return {
            "separation": bool(pipeline_opts.get("use_vocal_separator", True)),
            "asr": True,
            "translation": True,
            "tts": False,
            "mix": False,
        }
    if mode == PipelineMode.TTS_ONLY:
        return {
            "separation": bool(pipeline_opts.get("use_vocal_separator", True)),
            "asr": True,
            "translation": True,
            "tts": True,
            "mix": False,
        }
    if mode == PipelineMode.CUSTOM:
        return {
            "separation": bool(pipeline_opts.get("use_vocal_separator", True)),
            "asr": bool(pipeline_opts.get("use_asr", True)),
            "translation": bool(pipeline_opts.get("use_translate", True)),
            "tts": bool(pipeline_opts.get("use_tts", True)),
            "mix": bool(pipeline_opts.get("use_mixer", True)),
        }
    return {
        "separation": bool(pipeline_opts.get("use_vocal_separator", True)),
        "asr": True,
        "translation": True,
        "tts": True,
        "mix": True,
    }


def _build_separation(profile: dict[str, Any], pipeline_opts: dict[str, Any], *, enabled: bool) -> StageBinding:
    sep_profile = dict(profile.get("separator", {}))
    return StageBinding(
        kind=StageKind.SEPARATION,
        provider=sep_profile.get("provider", "builtin"),
        model=sep_profile.get("model", pipeline_opts.get("vocal_model", "htdemucs")),
        enabled=enabled,
        common_options=dict(sep_profile.get("common_options", {})),
        provider_options=dict(sep_profile.get("provider_options", {})),
    )


def _build_asr(
    profile: dict[str, Any],
    pipeline_opts: dict[str, Any],
    source_lang: str,
    *,
    enabled: bool,
) -> StageBinding:
    asr_profile = dict(profile.get("asr", {}))
    return StageBinding(
        kind=StageKind.ASR,
        provider=asr_profile.get("provider", "faster_whisper"),
        model=asr_profile.get("model", pipeline_opts.get("asr_model", "faster-whisper-base")),
        enabled=enabled,
        common_options={"language": source_lang, **dict(asr_profile.get("common_options", {}))},
        provider_options=dict(asr_profile.get("provider_options", {})),
    )


def _build_translation(profile: dict[str, Any], pipeline_opts: dict[str, Any], *, enabled: bool) -> StageBinding:
    llm_profile = dict(profile.get("llm", {}))
    return StageBinding(
        kind=StageKind.TRANSLATION,
        provider=llm_profile.get("provider", pipeline_opts.get("translate_provider", "deepseek")),
        model=llm_profile.get("model", "default"),
        enabled=enabled,
        common_options=dict(llm_profile.get("common_options", {})),
        provider_options=dict(llm_profile.get("provider_options", {})),
    )


def _build_tts(profile: dict[str, Any], pipeline_opts: dict[str, Any], *, enabled: bool) -> StageBinding:
    tts_profile = dict(profile.get("tts", {}))
    common = dict(tts_profile.get("common_options", {}))
    provider_opts = dict(tts_profile.get("provider_options", {}))
    # Keep the V1 common option compatible with runtimes that still read it
    # from provider_options during the transition.
    if "voice_profile_id" not in provider_opts:
        provider_opts["voice_profile_id"] = common.get(
            "voice_profile_id", pipeline_opts.get("voice_profile_id")
        )
    return StageBinding(
        kind=StageKind.TTS,
        provider=tts_profile.get("provider", pipeline_opts.get("tts_engine", "edge")),
        model=tts_profile.get("model", "default"),
        enabled=enabled,
        common_options={
            "voice": common.get("voice", pipeline_opts.get("tts_voice", "zh-CN-XiaoxiaoNeural")),
            "speed": float(common.get("speed", pipeline_opts.get("tts_speed", 1.0))),
        },
        provider_options=provider_opts,
    )


def _build_mix(profile: dict[str, Any], pipeline_opts: dict[str, Any], *, enabled: bool) -> MixConfig:
    mix_profile = dict(profile.get("mix", {}))
    mix_options = dict(mix_profile.get("common_options", mix_profile))
    if "tts_delay_ms" in mix_options:
        tts_delay_ms = float(mix_options["tts_delay_ms"])
    else:
        tts_delay_ms = float(
            mix_options.get("tts_delay", pipeline_opts.get("tts_delay", 0.0))
        ) * 1000
    return MixConfig(
        enabled=enabled,
        original_volume=float(mix_options.get("original_volume", pipeline_opts.get("original_volume", 0.85))),
        tts_volume_ratio=float(mix_options.get("tts_volume_ratio", pipeline_opts.get("tts_volume_ratio", 0.5))),
        tts_delay_ms=tts_delay_ms,
    )


def _build_subtitle(
    pipeline_opts: dict[str, Any],
    export_profile: dict[str, Any] | None = None,
    *,
    enabled: bool = True,
) -> SubtitleConfig:
    export_options = dict((export_profile or {}).get("common_options", {}))
    return SubtitleConfig(
        enabled=enabled,
        clean_enabled=bool(pipeline_opts.get("clean_subtitle", True)),
        clean_sound_effects=bool(pipeline_opts.get("clean_sound_effects", True)),
        clean_speaker_names=bool(pipeline_opts.get("clean_speaker_names", True)),
        export_format=str(
            export_options.get(
                "subtitle_format", pipeline_opts.get("export_subtitle_format", "srt")
            )
        ),
    )


def _is_mainline_v1(profile: dict[str, Any]) -> bool:
    return profile.get("profile_version") == "mainline.v1" or "profiles" in profile


def _is_stage_profile_v1(profile: dict[str, Any]) -> bool:
    return profile.get("version") == 1 and isinstance(profile.get("stages"), dict)


def _stage_profile(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": stage.get("provider", ""),
        "model": stage.get("model") or "default",
        "common_options": dict(stage.get("options", {})),
        "provider_options": dict(stage.get("provider_options", {})),
    }


def _stage_profile_parts(
    profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    stages = dict(profile.get("stages", {}))
    pipeline_opts = {
        "source_lang": profile.get("source_lang", "ja"),
        "target_lang": profile.get("target_lang", "zh"),
        "skip_existing": bool(profile.get("skip_existing", False)),
        "output_mode": "single",
        "batch_root_dir": "",
    }
    stage_profiles = {
        "separator": _stage_profile(dict(stages.get("separate", {}))),
        "asr": _stage_profile(dict(stages.get("asr", {}))),
        "llm": _stage_profile(dict(stages.get("translate", {}))),
        "tts": _stage_profile(dict(stages.get("tts", {}))),
        "mix": _stage_profile(dict(stages.get("mix", {}))),
        "export": _stage_profile(dict(stages.get("export", {}))),
    }
    stage_flags = {
        "separation": bool(dict(stages.get("separate", {})).get("enabled", True)),
        "asr": bool(dict(stages.get("asr", {})).get("enabled", True)),
        "translation": bool(dict(stages.get("translate", {})).get("enabled", True)),
        "tts": bool(dict(stages.get("tts", {})).get("enabled", True)),
        "mix": bool(dict(stages.get("mix", {})).get("enabled", True)),
        "export": bool(dict(stages.get("export", {})).get("enabled", True)),
    }
    return pipeline_opts, stage_profiles, stage_flags


def _mainline_parts(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, bool]]:
    """Adapt the V1 profile shape to the executor's internal bindings."""
    stages = dict(profile.get("stages", {}))
    profiles = dict(profile.get("profiles", {}))
    pipeline_opts = {
        "source_lang": profile.get("source_lang", "ja"),
        "target_lang": profile.get("target_lang", "zh"),
        "skip_existing": bool(profile.get("skip_existing", False)),
        # These fields are transitional runtime behavior used by batch callers.
        "output_mode": profile.get("output_mode", "single"),
        "batch_root_dir": profile.get("batch_root_dir", ""),
    }
    stage_profiles = {
        "separator": dict(profiles.get("separator", {})),
        "asr": dict(profiles.get("asr", {})),
        "llm": dict(profiles.get("translation", {})),
        "tts": dict(profiles.get("tts", {})),
        "mix": dict(profiles.get("mix", {})),
        "export": dict(profiles.get("export", {})),
    }
    stage_flags = {
        "separation": bool(stages.get("separate", True)),
        "asr": bool(stages.get("asr", True)),
        "translation": bool(stages.get("translate", True)),
        "tts": bool(stages.get("tts", True)),
        "mix": bool(stages.get("mix", True)),
        "export": bool(stages.get("export", True)),
    }
    return pipeline_opts, stage_profiles, stage_flags


def build_execution_plan(context: PipelineExecutionContext) -> PipelineExecutionPlan:
    """Build a PipelineExecutionPlan from an execution context."""
    profile = dict(context.execution_profile)
    if _is_stage_profile_v1(profile):
        pipeline_opts, stage_profiles, stage_flags = _stage_profile_parts(profile)
    elif _is_mainline_v1(profile):
        pipeline_opts, stage_profiles, stage_flags = _mainline_parts(profile)
    else:
        stage_profiles = dict(profile.get("stages", {}))
        pipeline_opts = dict(profile.get("pipeline", {}))
        mode_str = pipeline_opts.get("pipeline_mode", "full")
        try:
            legacy_mode = PipelineMode(mode_str)
        except ValueError:
            legacy_mode = PipelineMode.FULL
        stage_flags = _resolve_stage_flags(legacy_mode, pipeline_opts)
        stage_flags["export"] = True

    source_lang = pipeline_opts.get("source_lang", context.source_lang)
    target_lang = pipeline_opts.get("target_lang", context.target_lang)
    source_label, target_label = _resolve_lang_labels(source_lang, target_lang)

    mode_str = pipeline_opts.get("pipeline_mode", "full")
    try:
        mode = PipelineMode(mode_str)
    except ValueError:
        mode = PipelineMode.FULL
    return PipelineExecutionPlan(
        task_id=context.task_id,
        input_path=context.input_path,
        output_dir=context.output_dir,
        companion_subtitle_path=context.companion_subtitle_path,
        source_lang=source_lang,
        target_lang=target_lang,
        source_label=source_label,
        target_label=target_label,
        mode=mode,
        skip_existing=bool(pipeline_opts.get("skip_existing", False)),
        output_mode=str(pipeline_opts.get("output_mode", "single")),
        batch_root_dir=str(pipeline_opts.get("batch_root_dir", "")),
        separation=_build_separation(stage_profiles, pipeline_opts, enabled=stage_flags["separation"]),
        asr=_build_asr(stage_profiles, pipeline_opts, source_lang, enabled=stage_flags["asr"]),
        translation=_build_translation(stage_profiles, pipeline_opts, enabled=stage_flags["translation"]),
        tts=_build_tts(stage_profiles, pipeline_opts, enabled=stage_flags["tts"]),
        mix=_build_mix(
            stage_profiles
            if _is_stage_profile_v1(profile) or _is_mainline_v1(profile)
            else profile,
            pipeline_opts,
            enabled=stage_flags["mix"],
        ),
        subtitle=_build_subtitle(
            pipeline_opts,
            stage_profiles.get("export"),
            enabled=stage_flags["export"],
        ),
    )
