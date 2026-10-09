"""Built-in starter recipe, using the same catalog and compiler as user recipes."""
from .providers import get_provider


EDGE_STARTER_KEY = "edge-chinese-v1"


def edge_starter_recipe():
    catalog = get_provider("edge").voice_sources("builtin")
    speaker = catalog["default"]
    if not any(item["id"] == speaker for item in catalog["presets"]):
        raise ValueError("Edge default speaker is missing from the engine catalog")
    return {
        "name": "Edge 中文·晓晓",
        "description": "中文女声，正常语速。需联网使用 Edge 语音服务，不是离线模型。",
        "provider_id": "edge", "model": "edge-tts", "mode": "builtin",
        "connection_ref": "engine-default-edge",
        "variant": {"kind": "builtin", "value": speaker, "style": "normal"},
        "language": "zh", "provider_options": {"schema_version": 1, "speed": 1},
        "default_delivery": "normal", "default_emotion": "neutral", "default_pause_ms": 0,
    }
