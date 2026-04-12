"""Validation helpers for GUI-collected runtime parameters."""

from __future__ import annotations

from typing import Mapping, Sequence, Tuple


def validate_single_params(params: Mapping[str, object]) -> Tuple[bool, str]:
    required = ["tts_engine", "tts_voice", "vocal_model", "asr_model", "asr_language"]
    for key in required:
        if not params.get(key):
            return False, f"参数缺失: {key}"

    if params.get("tts_engine") not in {"edge", "qwen3"}:
        return False, "无效的 TTS 引擎"

    try:
        tts_speed = float(params.get("tts_speed", 1.0))
        orig = float(params.get("original_volume", 0.85))
        tts_ratio = float(params.get("tts_ratio", 0.5))
    except (TypeError, ValueError):
        return False, "音频参数格式错误"

    if not 0.1 <= tts_speed <= 3.0:
        return False, "语速范围应在 0.1-3.0"
    if not 0.0 <= orig <= 1.0:
        return False, "原音音量范围应在 0-1"
    if not 0.0 <= tts_ratio <= 1.0:
        return False, "配音音量范围应在 0-1"

    return True, ""


def validate_batch_params(params: Mapping[str, object], input_files: Sequence[str]) -> Tuple[bool, str]:
    if not input_files:
        return False, "没有可处理的输入文件"

    ok, msg = validate_single_params(params)
    if not ok:
        return ok, msg

    max_workers = params.get("max_workers", 1)
    try:
        workers = int(max_workers)
    except (TypeError, ValueError):
        return False, "并行度格式错误"

    if workers < 1 or workers > 4:
        return False, "并行度范围应在 1-4"

    return True, ""
