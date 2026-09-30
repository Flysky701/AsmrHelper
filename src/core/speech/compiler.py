"""Pure, deterministic compilation of recipes and exact-text speech plans."""
from copy import deepcopy
import hashlib
import json

from .providers import ProviderError, get_provider

COMPILER_VERSION = "1"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compile_recipe(recipe: dict, plan: dict, assets: dict[str, dict]) -> list[dict]:
    if not all(isinstance(value, dict) for value in (recipe, plan, assets)):
        raise ProviderError("invalid_input", "配方、方案和素材必须是对象")
    recipe, plan, assets = deepcopy(recipe), deepcopy(plan), deepcopy(assets)
    if not isinstance(plan.get("text"), str) or not plan["text"].strip():
        raise ProviderError("invalid_plan", "台词不能为空")
    text = plan["text"]
    if plan.get("text_hash") != text_hash(text):
        raise ProviderError("text_changed", "台词摘要与原文不符")
    if "use_recipe_defaults" in plan and type(plan["use_recipe_defaults"]) is not bool:
        raise ProviderError("invalid_plan", "use_recipe_defaults 必须是布尔值")
    if not recipe.get("id") or type(recipe.get("revision")) is not int:
        raise ProviderError("invalid_recipe", "配方必须具有 ID 和修订号")
    provider = get_provider(recipe.get("provider_id"))
    provider.validate(recipe, assets)
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ProviderError("invalid_plan", "演绎方案必须包含片段")
    cursor, ids, compiled = 0, set(), []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ProviderError("invalid_plan", "片段必须是对象")
        if plan.get("use_recipe_defaults") is True:
            segment = {**segment, "delivery": recipe.get("default_delivery", "normal"),
                       "emotion": recipe.get("default_emotion", "neutral"),
                       "pause_ms": recipe.get("default_pause_ms", 0)}
        start, end, sid = segment.get("start"), segment.get("end"), segment.get("id")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ProviderError("invalid_plan", "片段 ID 必须唯一且非空")
        ids.add(sid)
        if type(start) is not int or type(end) is not int or start != cursor or not start < end <= len(text):
            raise ProviderError("invalid_offsets", "片段必须连续覆盖原文，不能改写或遗漏台词")
        cursor = end
        pause = segment.get("pause_ms", 0)
        if type(pause) is not int or not 0 <= pause <= 30000:
            raise ProviderError("invalid_pause", "停顿须为 0–30000 毫秒整数")
        segment_text = text[start:end]
        if "text" in segment and segment["text"] != segment_text:
            raise ProviderError("text_changed", "片段文本与原文位置不符")
        parameters = provider.compile(recipe, segment, segment_text, assets)
        hashes = {}
        if recipe["variant"]["kind"] == "reference":
            aid = recipe["variant"]["value"]
            hashes[aid] = assets[aid]["sha256"]
        request = {
            "provider_id": provider.provider_id, "provider_version": provider.version,
            "compiler_version": COMPILER_VERSION, "model": recipe["model"], "mode": recipe["mode"],
            "connection_ref": recipe.get("connection_ref"), "segment_id": sid,
            "text": segment_text, "text_hash": text_hash(segment_text), "pause_ms": pause,
            "parameters": parameters, "asset_hashes": hashes,
            "warnings": ["远端模型版本与声音效果尚未实测，无法保证完全复现"] if provider.remote else [],
            "recipe_id": recipe["id"], "recipe_revision": recipe["revision"],
        }
        encoded = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False)
        request["cache_key"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        request["id"] = request["cache_key"]
        compiled.append(request)
    if cursor != len(text):
        raise ProviderError("invalid_offsets", "片段未覆盖完整台词")
    return compiled
