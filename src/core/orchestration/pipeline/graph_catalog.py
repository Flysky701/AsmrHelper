"""Finite graph capabilities backed by the existing engine adapters."""
from __future__ import annotations

from copy import deepcopy


GRAPH_CATALOG = {
    "separate": {"label": "人声分离", "inputs": {"audio": "audio"}, "outputs": {"audio": "audio"}},
    "asr": {"label": "语音识别", "inputs": {"audio": "audio"}, "outputs": {"subtitle": "subtitle"}},
    "align": {"label": "时间轴校准", "inputs": {"audio": "audio", "subtitle": "subtitle"}, "outputs": {"subtitle": "subtitle"}},
    "translate": {"label": "字幕翻译", "inputs": {"subtitle": "subtitle"}, "outputs": {"subtitle": "subtitle"}},
    "tts": {"label": "语音合成", "inputs": {"subtitle": "subtitle"}, "outputs": {"audio": "audio"}},
    "mix": {"label": "混音", "inputs": {"audio": "audio", "speech": "audio"}, "outputs": {"audio": "audio"}},
    "audio_difference": {"label": "音频差分", "inputs": {"reference": "audio", "mixed": "audio"}, "outputs": {"audio": "audio"}},
    "export": {"label": "字幕格式转换", "inputs": {"subtitle": "subtitle"}, "outputs": {"subtitle": "subtitle"}},
    "audio_export": {"label": "音频导出", "inputs": {"audio": "audio"}, "outputs": {"audio": "audio"}},
}
GRAPH_NODE_KINDS = tuple(GRAPH_CATALOG)
GRAPH_LANGUAGES = ("ja", "zh", "en")
GRAPH_PORT_TYPES = ("audio", "subtitle")
# None delegates the option schema to the existing provider descriptor validator.
GRAPH_OPTION_KEYS = {
    "separate": ("mode",), "asr": None, "align": (), "translate": None,
    "tts": ("speech_recipe_id", "speech_overrides", "speech_source", "voice", "speed"),
    "mix": ("original_volume", "tts_volume_ratio", "tts_delay_ms", "output_length", "tracks"),
    "audio_difference": ("alignment", "offset_ms", "match_gain", "gain_left", "gain_right",
                         "calibration_start", "calibration_end", "max_shift_seconds"),
    "export": ("subtitle_format",),
    "audio_export": (),
}


def is_multitrack(node: dict) -> bool:
    return node.get("kind") == "mix" and "tracks" in node.get("options", {})


def input_ports(node: dict) -> dict[str, str]:
    """Resolve stable instance ports; absent tracks retains the legacy contract."""
    if is_multitrack(node):
        return {track["id"]: "audio" for track in node["options"]["tracks"]}
    return GRAPH_CATALOG[node["kind"]]["inputs"]


def graph_catalog() -> dict:
    """Return a copy so callers cannot change the authoritative port definitions."""
    return deepcopy(GRAPH_CATALOG)


def capabilities() -> list[dict]:
    # Keep legacy nodes in the execution catalog without offering new copies.
    return [{"kind": kind, **deepcopy(value), "option_keys": GRAPH_OPTION_KEYS[kind]}
            for kind, value in GRAPH_CATALOG.items() if kind != "audio_export"]
