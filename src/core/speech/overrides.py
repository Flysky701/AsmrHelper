"""Apply one task's supported performance adjustments without changing its voice."""
from copy import deepcopy


def apply_speech_overrides(recipe, overrides, provider):
    if not isinstance(overrides, dict) or set(overrides) - {
        "provider_options", "default_delivery", "default_emotion", "default_pause_ms"
    }:
        raise ValueError("本次微调包含不支持的字段；声音来源请在音色库编辑")
    options = overrides.get("provider_options", {})
    allowed = getattr(provider, "runtime_options", lambda model, mode: [])(recipe["model"], recipe["mode"])
    if not isinstance(options, dict) or set(options) - set(allowed):
        raise ValueError("当前引擎或模式不支持这些本次微调参数")
    caps = provider.capabilities(recipe["model"], recipe["mode"])
    if "default_delivery" in overrides:
        value = overrides["default_delivery"]
        if not isinstance(value, str) or caps.get("delivery", {}).get(value, {}).get("support") != "direct":
            raise ValueError("当前模式不支持此演绎微调")
    if "default_emotion" in overrides:
        value = overrides["default_emotion"]
        if not isinstance(value, str) or caps.get("emotion", {}).get("support") != "direct":
            raise ValueError("当前模式不支持情绪微调")
    if "default_pause_ms" in overrides:
        value = overrides["default_pause_ms"]
        if caps.get("pause", {}).get("support") != "postprocess" or type(value) is not int or not 0 <= value <= 30000:
            raise ValueError("句后停顿须为 0–30000 毫秒整数")
    result = deepcopy(recipe)
    result["provider_options"] = {**result.get("provider_options", {"schema_version": 1}), **deepcopy(options)}
    for key in ("default_delivery", "default_emotion", "default_pause_ms"):
        if key in overrides:
            result[key] = overrides[key]
    # Validate values using the same engine schema as saved presets. Compilation
    # subsequently validates mode-specific intent and reference requirements.
    validate_options = getattr(provider, "_options", None)
    if callable(validate_options):
        validate_options(result)
    return result
