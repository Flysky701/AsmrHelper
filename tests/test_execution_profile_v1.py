from __future__ import annotations

from src.core.orchestration.pipeline import PipelineExecutionContext, build_execution_plan


def test_planner_consumes_unified_stage_profiles():
    context = PipelineExecutionContext(
        task_id="pipeline-v1",
        input_path="C:/input/demo.wav",
        output_dir="C:/output",
        execution_profile={
            "version": 1,
            "source_lang": "ja",
            "target_lang": "zh",
            "skip_existing": True,
            "stages": {
                "separate": {
                    "enabled": False,
                    "provider": "htdemucs",
                    "model": "htdemucs",
                    "options": {"mode": "vocals"},
                    "provider_options": {},
                },
                "asr": {
                    "enabled": True,
                    "provider": "faster_whisper",
                    "model": "faster-whisper-small",
                    "options": {"language": "ja", "timestamps": True},
                    "provider_options": {"disable_vad": True},
                },
                "translate": {
                    "enabled": True,
                    "provider": "deepseek",
                    "model": None,
                    "options": {"target_lang": "zh"},
                    "provider_options": {},
                },
                "tts": {
                    "enabled": True,
                    "provider": "edge",
                    "model": None,
                    "options": {
                        "voice": "zh-CN-XiaoxiaoNeural",
                        "speed": 1.1,
                    },
                    "provider_options": {},
                },
                "mix": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {
                        "original_volume": 0.7,
                        "tts_volume_ratio": 0.4,
                        "tts_delay_ms": 250,
                    },
                    "provider_options": {},
                },
                "export": {
                    "enabled": True,
                    "provider": "ffmpeg",
                    "model": None,
                    "options": {"subtitle_format": "vtt"},
                    "provider_options": {},
                },
            },
        },
    )

    plan = build_execution_plan(context)

    assert plan.source_lang == "ja"
    assert plan.target_lang == "zh"
    assert plan.skip_existing is True
    assert plan.separation.enabled is False
    assert plan.separation.provider == "htdemucs"
    assert plan.asr.model == "faster-whisper-small"
    assert plan.asr.provider_options["disable_vad"] is True
    assert plan.translation.model == "default"
    assert plan.tts.common_options["speed"] == 1.1
    assert plan.mix.original_volume == 0.7
    assert plan.mix.tts_delay_ms == 250
    assert plan.subtitle.export_format == "vtt"


def test_planner_consumes_mainline_v1_profile():
    context = PipelineExecutionContext(
        task_id="pipeline-1",
        input_path="C:/input/demo.wav",
        output_dir="C:/output",
        execution_profile={
            "profile_version": "mainline.v1",
            "source_lang": "ja",
            "target_lang": "zh",
            "skip_existing": True,
            "stages": {
                "separate": False,
                "asr": True,
                "translate": True,
                "tts": False,
                "mix": False,
                "export": False,
            },
            "profiles": {
                "separator": {"provider": "builtin", "model": "htdemucs"},
                "asr": {
                    "provider": "faster_whisper",
                    "model": "faster-whisper-base",
                    "common_options": {"language": "ja", "timestamps": True},
                },
                "translation": {
                    "provider": "deepseek",
                    "model": "default",
                    "common_options": {"target_lang": "zh"},
                },
                "tts": {"provider": "edge", "model": "default"},
                "mix": {"common_options": {"original_volume": 0.7}},
                "export": {"common_options": {"subtitle_format": "vtt"}},
            },
        },
    )

    plan = build_execution_plan(context)

    assert plan.source_lang == "ja"
    assert plan.target_lang == "zh"
    assert plan.skip_existing is True
    assert plan.separation.enabled is False
    assert plan.asr.enabled is True
    assert plan.translation.enabled is True
    assert plan.tts.enabled is False
    assert plan.mix.enabled is False
    assert plan.subtitle.enabled is False
    assert plan.asr.common_options["timestamps"] is True
    assert plan.mix.original_volume == 0.7


def test_planner_keeps_legacy_profile_compatible():
    context = PipelineExecutionContext(
        task_id="pipeline-legacy",
        input_path="C:/input/demo.wav",
        output_dir="C:/output",
        execution_profile={
            "pipeline": {
                "source_lang": "en",
                "target_lang": "zh",
                "use_vocal_separator": False,
                "skip_existing": True,
            },
            "stages": {
                "asr": {"provider": "faster_whisper", "model": "base"},
                "llm": {"provider": "deepseek", "model": "default"},
                "tts": {"provider": "edge", "model": "default"},
            },
            "mix": {"original_volume": 0.6},
        },
    )

    plan = build_execution_plan(context)

    assert plan.source_lang == "en"
    assert plan.separation.enabled is False
    assert plan.skip_existing is True
    assert plan.mix.original_volume == 0.6
