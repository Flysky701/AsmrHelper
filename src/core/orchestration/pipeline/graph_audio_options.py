"""Portable options for local graph audio operations (no paths or runtime state)."""
from __future__ import annotations

import math
import re


def validate_audio_options(node, add):
    options = node.get("options")
    if not isinstance(options, dict):
        return

    def number(key, default, minimum=None, maximum=None):
        value = options.get(key, default)
        valid = type(value) in (int, float) and math.isfinite(value)
        valid = valid and (minimum is None or value >= minimum)
        valid = valid and (maximum is None or value <= maximum)
        if not valid:
            add("invalid_option", f"{key} 必须是允许范围内的有限数值", node["id"])
        return valid

    if node.get("kind") == "mix" and "tracks" in options:
        if options.keys() & {"original_volume", "tts_volume_ratio", "tts_delay_ms"}:
            add("invalid_option", "多轨混音不能同时使用旧双轨音量参数", node["id"])
        tracks = options["tracks"]
        if not isinstance(tracks, list) or not 1 <= len(tracks) <= 32:
            add("invalid_option", "混音需要 1 至 32 条音轨", node["id"])
            return
        seen = set()
        for track in tracks:
            if not isinstance(track, dict) or track.keys() - {"id", "gain", "offset_ms", "muted"}:
                add("invalid_option", "音轨参数只支持 id、gain、offset_ms、muted", node["id"])
                continue
            track_id = track.get("id")
            if (not isinstance(track_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", track_id)
                    or track_id.casefold() in seen):
                add("invalid_option", "音轨编号无效或重复", node["id"])
            else:
                seen.add(track_id.casefold())
            for key, default in (("gain", 1), ("offset_ms", 0)):
                value = track.get(key, default)
                if (type(value) not in (int, float) or not math.isfinite(value)
                        or key == "gain" and value < 0):
                    add("invalid_option", f"音轨 {key} 必须有限，音量不能为负数", node["id"])
            if type(track.get("muted", False)) is not bool:
                add("invalid_option", "音轨 muted 必须是布尔值", node["id"])
    elif node.get("kind") == "audio_difference":
        if options.get("alignment", "manual") not in ("manual", "auto"):
            add("invalid_option", "alignment 必须是 manual 或 auto", node["id"])
        if type(options.get("match_gain", False)) is not bool:
            add("invalid_option", "match_gain 必须是布尔值", node["id"])
        for key, default in (("offset_ms", 0), ("gain_left", 1), ("gain_right", 1)):
            number(key, default)
        number("max_shift_seconds", 5, .01, 30)
        start_valid = number("calibration_start", 0, 0)
        if "calibration_end" in options:
            end_valid = number("calibration_end", None, 0)
            if start_valid and end_valid and options["calibration_end"] <= options.get("calibration_start", 0):
                add("invalid_option", "校准终点必须晚于起点", node["id"])
