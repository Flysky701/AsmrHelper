"""Explicit speech provider contracts; no voice-profile or configuration fallback."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import numpy as np
import soundfile as sf


class ProviderError(ValueError):
    def __init__(self, code, message, *, retryable=False, result_unknown=False):
        super().__init__(message)
        self.code, self.retryable, self.result_unknown = code, retryable, result_unknown
        self.task_error = {"code": code, "detail": message, "result_unknown": result_unknown,
            "retryable": retryable, "stage": "tts"}


def _cancel(check):
    if check and check():
        raise ProviderError("cancelled", "语音生成已取消")


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redact_secret(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _number(minimum, maximum, default):
    return {"type": "number", "minimum": minimum, "maximum": maximum, "default": default}


COMMON = {"schema_version": {"type": "integer", "const": 1, "default": 1}}
SCHEMAS = {
    "fish_audio": {**COMMON, "speed": _number(.5, 2, 1), "temperature": _number(0, 1, .7),
        "top_p": _number(0, 1, .7), "style_description": {"type": "string", "maxLength": 300, "default": ""},
        "tag_density": {"type": "string", "enum": ["minimal", "full"], "default": "minimal"}},
    "openai_compatible": {**COMMON, "speed": _number(.25, 4, 1)},
    "edge": {**COMMON, "speed": _number(.5, 2, 1)},
    "qwen3": {**COMMON, "temperature": {**_number(.01, 2, .9), "title": "随机温度"},
        "top_p": {**_number(.01, 1, 1), "title": "累积概率"},
        "x_vector_only_mode": {"type": "boolean", "default": False, "title": "仅使用声音特征",
            "description": "仅参考克隆模式；仍需参考音频，可不填写原文。关闭时必须核对参考原文。",
            "applies_to_modes": ["reference"]},
        "do_sample": {"type": "boolean", "default": True, "title": "启用随机采样",
            "description": "控制主生成的随机采样；关闭时主生成的温度、Top P、Top K 不参与随机采样，不保证音频逐次相同。"},
        "top_k": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 50,
            "title": "候选数量", "description": "每步采样的候选数量；0 表示不按数量截断。"},
        "repetition_penalty": {**_number(.1, 10, 1.05), "title": "重复惩罚",
            "description": "1 不施加惩罚；大于 1 抑制重复。"},
        "max_new_tokens": {"type": "integer", "minimum": 1, "maximum": 8192, "default": 2048,
            "title": "最大生成长度", "description": "生成 token 上限；过小可能截断语音，不等于秒数。"}},
    "voxcpm2": {**COMMON, "cfg_value": _number(.1, 10, 2),
        "inference_timesteps": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}},
}
MODES = {
    "fish_audio": [{"id": "hosted", "variant_kinds": ["hosted"], "models": ["s2.1-pro-free", "s2.1-pro", "s2-pro", "s1"]}],
    "openai_compatible": [{"id": "hosted", "variant_kinds": ["hosted"], "models": []}],
    "edge": [{"id": "builtin", "variant_kinds": ["builtin"], "models": ["edge-tts"]}],
    "qwen3": [
        {"id": "builtin", "variant_kinds": ["builtin"], "models": ["qwen3-custom-voice"]},
        {"id": "reference", "variant_kinds": ["reference"], "models": ["qwen3-base"]},
        {"id": "design", "variant_kinds": ["design"], "models": ["qwen3-voice-design"]}],
    "voxcpm2": [{"id": mode, "variant_kinds": [mode], "models": ["voxcpm2"]} for mode in ("default", "reference", "design")],
}
_LOCAL_LOCK = threading.Lock()
EMOTIONS = {"neutral", "happy", "sad", "angry", "excited", "calm", "nervous", "relaxed"}
STYLE_TEXT = {"normal": "", "soft": "轻柔自然地说话", "whisper": "以清晰气声耳语说话"}

# Consumption controls only. Voice identity, reference conditioning and execution
# settings never enter this list, even if a future engine declares such options.
RUNTIME_OPTIONS = {
    "fish_audio": ("speed", "temperature", "top_p", "style_description", "tag_density"),
    "openai_compatible": ("speed",),
    "edge": ("speed",),
    "qwen3": ("temperature", "top_p", "do_sample", "top_k", "repetition_penalty", "max_new_tokens"),
    "voxcpm2": ("cfg_value", "inference_timesteps"),
}


class SpeechProvider:
    version = "1"

    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.remote = provider_id in {"fish_audio", "openai_compatible", "edge"}
        self.http = provider_id in {"fish_audio", "openai_compatible"}
        self.options_schema, self.modes = SCHEMAS[provider_id], MODES[provider_id]

    def capabilities(self, model=None, mode=None):
        express = self.provider_id in {"fish_audio", "voxcpm2"} or (self.provider_id == "qwen3" and mode != "reference")
        support = "direct" if express else ("reference" if mode == "reference" else "unsupported")
        return {"delivery": {k: {"support": "direct" if k == "normal" else support, "evidence": "unverified"}
                for k in STYLE_TEXT}, "emotion": {"support": "direct" if express else "unsupported", "evidence": "unverified"},
            "pause": {"support": "postprocess", "evidence": "tested"}, "streaming": False,
            "cancellation": "between_segments" if self.remote else "worker_termination",
            "concurrency": 1 if not self.remote else None,
            "languages": ["zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"] if self.provider_id == "qwen3" else "model-dependent",
            "reference": {"supported": mode == "reference", "transcript_required": self.provider_id == "qwen3" and mode == "reference",
                "transcript_optional_option": "x_vector_only_mode" if self.provider_id == "qwen3" and mode == "reference" else None,
                "duration_limit_seconds": None, "upload": False}, "max_text_length": None}

    def runtime_options(self, model, mode):
        if not any(item["id"] == mode and (not item["models"] or model in item["models"]) for item in self.modes):
            return []
        return [key for key in RUNTIME_OPTIONS.get(self.provider_id, ())
                if key in self.options_schema
                and (not self.options_schema[key].get("applies_to_modes") or mode in self.options_schema[key]["applies_to_modes"])
                and not (self.provider_id == "fish_audio" and model == "s1" and key in {"style_description", "tag_density"})]

    def describe(self):
        modes = deepcopy(self.modes)
        for mode in modes:
            mode["capabilities"] = self.capabilities(mode["models"][0] if mode["models"] else None, mode["id"])
            mode["voice_sources"] = self.voice_sources(mode["id"])
            mode["runtime_options"] = self.runtime_options(mode["models"][0] if mode["models"] else None, mode["id"])
            mode["model_capabilities"] = {model: self.capabilities(model, mode["id"]) for model in mode["models"]}
            mode["model_runtime_options"] = {model: self.runtime_options(model, mode["id"]) for model in mode["models"]}
        return deepcopy({"provider_id": self.provider_id, "name": {"fish_audio": "Fish Audio", "edge": "Edge TTS",
            "qwen3": "Qwen3 TTS", "voxcpm2": "VoxCPM2", "openai_compatible": "OpenAI 兼容语音"}.get(self.provider_id, getattr(self, "name", self.provider_id)),
            "version": self.version, "contract_version": 1, "remote": self.remote,
            "connection_required": self.http,
            "default_base_url": getattr(self, "default_base_url", None),
            "modes": modes, "options_schema": {"type": "object", "additionalProperties": False,
            "properties": self.options_schema}, "capabilities": self.capabilities()})

    def voice_sources(self, mode):
        """Offline catalog from actual engine presets; never invent hosted IDs."""
        presets, default = [], None
        if self.provider_id == "edge" and mode == "builtin":
            from src.core.tts import EdgeTTSEngine
            presets, default = EdgeTTSEngine.list_voices(), "zh-CN-XiaoxiaoNeural"
        elif self.provider_id == "qwen3" and mode == "builtin":
            from .qwen_catalog import list_qwen_voices
            presets, default = list_qwen_voices(), "Vivian"
        elif self.provider_id == "voxcpm2" and mode == "default":
            default = "default"
        return {"kind": mode, "presets": presets, "default": default,
                "required": default is None,
                "allow_custom": mode != "default" and not (self.provider_id == "qwen3" and mode == "builtin"),
                "description": "文本驱动，无固定说话人保证" if mode == "default" else
                    {"hosted": "填写服务端真实 Voice ID", "reference": "选择参考音频素材",
                     "design": "填写声音描述", "builtin": "选择引擎预设音色"}.get(mode, "")}

    def list_hosted_voices(self, context, *, title="", page=1, page_size=20, workspace_only=True, scope=None):
        """Read Fish's voice catalog without synthesis or a guessed default voice."""
        if self.provider_id != "fish_audio":
            raise ProviderError("voice_catalog_unsupported", "此引擎不支持获取声音列表，请手填 Voice ID")
        if not 1 <= page_size <= 100 or page < 1 or len(title) > 200:
            raise ValueError("声音查询参数无效")
        scope = scope or ("workspace" if workspace_only else "public")
        if scope not in {"workspace", "mine_public", "public"}:
            raise ValueError("未知声音查询范围")
        connection = context.get("connection", {})
        base = str(connection.get("base_url", "")).rstrip("/")
        key = connection.get("api_key")
        parsed = urlsplit(base)
        if (not key or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ProviderError("connection_missing", "服务连接地址或凭据不完整，请检查连接或手填 Voice ID")
        if connection.get("provider_id") != self.provider_id:
            raise ProviderError("connection_mismatch", "请选择 Fish Audio 服务连接")
        # Official TTS uses /v1/tts, while the voice catalog is at /model.
        # Keep a custom proxy's prefix; unsupported proxies fall back to manual IDs.
        path = parsed.path.rstrip("/")
        if parsed.hostname == "api.fish.audio" and path in {"", "/v1", "/tts", "/v1/tts"}:
            path = ""
        elif path.endswith("/tts"):
            path = path[:-4]
        url = parsed._replace(path=path + "/model").geturl()
        params = {"page_number": page, "page_size": page_size,
                  "self": "true" if scope == "workspace" else "false"}
        if title.strip():
            params["title"] = title.strip()
        owner_id = None
        if scope == "mine_public" and (parsed.scheme != "https" or parsed.hostname != "api.fish.audio"
                                       or parsed.port not in (None, 443) or path):
            raise ProviderError("voice_owner_unsupported", "此代理无法核实当前账号，请选工作区或公共库，或手填 Voice ID")
        try:
            with httpx.Client(timeout=httpx.Timeout(20, connect=10), follow_redirects=False) as client:
                if scope == "mine_public":
                    # Official /wallet/self/package resolves the authenticated user.
                    # Read only user_id; never expose or persist subscription/balance fields.
                    identity = client.get("https://api.fish.audio/wallet/self/package",
                                          headers={"Authorization": f"Bearer {key}"})
                    if identity.status_code != 200:
                        raise ProviderError("voice_owner_unavailable", "无法核实当前 API 账号，请检查权限或手填 Voice ID；未查询公共库")
                    try:
                        payload = identity.json()
                    except ValueError:
                        payload = None
                    owner_id = payload.get("user_id") if isinstance(payload, dict) else None
                    if (not isinstance(owner_id, str) or not owner_id.strip() or len(owner_id) > 200
                            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in owner_id)):
                        raise ProviderError("voice_owner_invalid", "未取得有效账号标识，请手填 Voice ID；未查询公共库")
                    params["author_id"] = owner_id
                response = client.get(url, params=params, headers={"Authorization": f"Bearer {key}"})
        except httpx.TimeoutException as exc:
            raise ProviderError("voice_catalog_timeout", "声音列表请求超时，请重试或手填 Voice ID") from exc
        except httpx.RequestError as exc:
            raise ProviderError("voice_catalog_network", "无法连接声音列表服务，请重试或手填 Voice ID") from exc
        if response.status_code in {401, 403}:
            raise ProviderError("voice_catalog_unauthorized", "无权读取声音列表，请检查连接权限或手填 Voice ID")
        if response.status_code in {404, 405, 501} or response.is_redirect:
            raise ProviderError("voice_catalog_unsupported", "当前服务或代理不支持声音列表，请手填 Voice ID")
        if response.status_code == 429:
            raise ProviderError("voice_catalog_rate_limited", "声音列表请求过于频繁，请稍后重试或手填 Voice ID")
        if response.status_code != 200:
            raise ProviderError("voice_catalog_failed", "声音列表服务暂不可用，请重试或手填 Voice ID")
        # Never expose upstream error bodies, headers or credentials to the UI.
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("voice_catalog_invalid", "服务未返回有效声音列表，请手填 Voice ID") from exc
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ProviderError("voice_catalog_invalid", "服务返回的声音列表格式不兼容，请手填 Voice ID")
        items, seen = [], set()
        for item in data["items"]:
            if (not isinstance(item, dict) or not isinstance(item.get("_id"), str)
                    or not item["_id"].strip() or not isinstance(item.get("title", ""), str)):
                raise ProviderError("voice_catalog_invalid", "服务返回的声音条目格式不兼容，请手填 Voice ID")
            if owner_id and (not isinstance(item.get("author"), dict)
                             or item["author"].get("_id") != owner_id or item.get("visibility") != "public"):
                raise ProviderError("voice_owner_mismatch", "服务返回的音色作者或公开范围不符，请手填 Voice ID；不会作为本人库展示")
            voice_id = item["_id"].strip()
            if voice_id not in seen:
                items.append({"id": voice_id, "name": item.get("title", "").strip() or voice_id})
                seen.add(voice_id)
        total = data.get("total")
        has_more = data.get("has_more")
        if not isinstance(has_more, bool):
            has_more = page * page_size < total if type(total) is int and total >= 0 else len(data["items"]) >= page_size
        has_more = bool(items) and has_more
        return {"items": items, "page": page, "page_size": page_size, "has_more": has_more, "scope": scope,
                "notice": "已到服务端可浏览范围，请按名称缩小搜索。" if data.get("window_limited") and not has_more else ""}

    def _options(self, recipe):
        options = recipe.get("provider_options", {})
        schema = self.options_schema
        if not isinstance(options, dict) or set(options) - set(schema) or options.get("schema_version") != 1:
            raise ProviderError("invalid_options", "引擎参数版本无效或包含未知字段")
        resolved = {}
        for key, rule in schema.items():
            if rule.get("applies_to_models") and recipe.get("model") not in rule["applies_to_models"]:
                if key in options:
                    raise ProviderError("invalid_options", f"当前模型不支持参数：{key}")
                continue
            rule = {**rule, **rule.get("model_overrides", {}).get(recipe.get("model"), {})}
            value = options.get(key, rule.get("default"))
            valid = ((rule["type"] == "number" and type(value) in (int, float) and math.isfinite(value))
                or (rule["type"] == "integer" and type(value) is int)
                or (rule["type"] == "boolean" and type(value) is bool)
                or (rule["type"] == "string" and isinstance(value, str)))
            if not valid or ("const" in rule and value != rule["const"]) or ("enum" in rule and value not in rule["enum"]):
                raise ProviderError("invalid_options", f"无效引擎参数：{key}")
            if ("minimum" in rule and value < rule["minimum"]) or ("maximum" in rule and value > rule["maximum"]) or ("maxLength" in rule and len(value) > rule["maxLength"]):
                raise ProviderError("invalid_options", f"引擎参数超出范围：{key}")
            resolved[key] = value
        return resolved

    def reference_requires_transcript(self, recipe):
        return (self.provider_id == "qwen3" and recipe.get("mode") == "reference"
                and not self._options(recipe)["x_vector_only_mode"])

    def validate(self, recipe, assets):
        options = self._options(recipe)
        if self.provider_id == "qwen3" and options["x_vector_only_mode"] and recipe.get("mode") != "reference":
            raise ProviderError("invalid_options", "仅使用声音特征只适用于 Qwen 参考克隆模式")
        mode = next((m for m in self.modes if m["id"] == recipe.get("mode")), None)
        variant = recipe.get("variant", {})
        if not isinstance(variant, dict) or set(variant) - {"kind", "value", "style"}:
            raise ProviderError("invalid_variant", "声音来源包含未知字段")
        if not isinstance(recipe.get("language", "auto"), str):
            raise ProviderError("invalid_language", "语言必须是明确的语言标识")
        if self.provider_id == "qwen3" and recipe.get("language", "auto").strip().lower().replace("_", "-").split("-", 1)[0] not in {
            "auto", "zh", "en", "ja", "jp", "ko", "de", "fr", "ru", "pt", "es", "it",
            "chinese", "english", "japanese", "korean", "german", "french", "russian", "portuguese", "spanish", "italian"}:
            raise ProviderError("invalid_language", "Qwen 模型不支持该语言")
        if recipe.get("connection_ref") is not None and not isinstance(recipe["connection_ref"], str):
            raise ProviderError("invalid_connection", "连接必须使用独立引用，不能包含凭据")
        if not mode or variant.get("kind") not in mode["variant_kinds"]:
            raise ProviderError("invalid_mode", "声音来源与引擎模式不匹配")
        model = recipe.get("model")
        if not isinstance(model, str) or not model.strip() or (mode["models"] and model not in mode["models"]):
            raise ProviderError("invalid_model", "模型与引擎模式不匹配")
        if not isinstance(variant.get("value"), str) or not variant["value"].strip() or variant.get("style", "normal") not in STYLE_TEXT:
            raise ProviderError("invalid_variant", "声音版本必须有明确来源和有效风格")
        if variant["kind"] == "default" and variant["value"] != "default":
            raise ProviderError("invalid_variant", "默认发声不能指定虚构音色")
        if self.provider_id == "qwen3" and recipe["mode"] == "builtin":
            if variant["value"] not in {v["id"] for v in self.voice_sources("builtin")["presets"]}:
                raise ProviderError("invalid_variant", "请选择 Qwen CustomVoice 的真实预设音色")
        if self.http and not recipe.get("connection_ref"):
            raise ProviderError("connection_missing", "请明确选择外部连接")
        if variant["kind"] == "reference":
            asset = assets.get(variant["value"], {})
            if not isinstance(asset, dict):
                raise ProviderError("asset_missing", "参考素材信息无效")
            digest = asset.get("sha256", "")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ProviderError("asset_missing", "参考素材不存在或缺少可信摘要")
            if self.reference_requires_transcript(recipe) and not str(asset.get("transcript", "")).strip():
                raise ProviderError("transcript_missing", "Qwen 参考素材需要确认转录")

    def compile(self, recipe, segment, text, assets):
        self.validate(recipe, assets)
        options, variant = self._options(recipe), recipe["variant"]
        delivery, emotion = segment.get("delivery", "normal"), segment.get("emotion", "neutral")
        if delivery not in STYLE_TEXT or emotion not in EMOTIONS:
            raise ProviderError("unsupported_intent", "未知发声方式或情绪")
        caps = self.capabilities(recipe["model"], recipe["mode"])
        if delivery != "normal" and caps["delivery"][delivery]["support"] != "direct" and variant.get("style", "normal") != delivery:
            raise ProviderError("unsupported_intent", "当前引擎需要对应风格的声音版本，不能直接转换发声方式")
        if emotion != "neutral" and caps["emotion"]["support"] != "direct":
            raise ProviderError("unsupported_intent", "此模型模式不支持独立情绪控制")
        params = {"language": recipe.get("language", "auto"), "variant": deepcopy(variant), "options": options,
            "delivery": delivery, "emotion": emotion}
        if self.provider_id == "fish_audio":
            cues = []
            if delivery != "normal":
                cues.append({"whisper": "whispering", "soft": "soft tone"}[delivery])
            if emotion != "neutral":
                cues.append(emotion)
            desc = options["style_description"].strip()
            if desc:
                if recipe["model"] == "s1":
                    raise ProviderError("unsupported_intent", "自由描述标签仅支持 Fish S2 系列")
                if any(c in desc for c in "[]\r\n"):
                    raise ProviderError("invalid_options", "风格描述不能含标签边界或换行")
                cues.append(desc)
            left, right = ("(", ")") if recipe["model"] == "s1" else ("[", "]")
            if options["tag_density"] == "minimal" and recipe["model"] != "s1" and cues:
                cues = [", ".join(cues)]
            params["rendered_text"] = "".join(left + cue + right for cue in cues) + text
        elif self.provider_id in {"qwen3", "voxcpm2"}:
            params["instruction"] = "，".join(x for x in [STYLE_TEXT[delivery], "" if emotion == "neutral" else emotion] if x)
            if variant["kind"] == "reference":
                params["reference_transcript"] = str(assets[variant["value"]].get("transcript", ""))
        return params

    def _has_remote_worker(self, context: dict | None) -> bool:
        if self.provider_id not in {"qwen3", "voxcpm2"}:
            return False
        ctx = context if isinstance(context, dict) else {}
        conn = ctx.get("connection") if isinstance(ctx.get("connection"), dict) else {}
        if _clean_str(conn.get("deployment")) == "remote_gpu":
            return True
        return bool(
            _clean_str(conn.get("base_url"))
            or _clean_str(conn.get("remote_worker_url"))
            or _clean_str(ctx.get("remote_worker_url"))
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_URL"))
        )

    def _resolve_remote_worker_config(
        self, context: dict | None
    ) -> tuple[str, str | None, float, Any]:
        ctx = context if isinstance(context, dict) else {}
        conn = ctx.get("connection") if isinstance(ctx.get("connection"), dict) else {}
        url = (
            _clean_str(conn.get("base_url"))
            or _clean_str(conn.get("remote_worker_url"))
            or _clean_str(ctx.get("remote_worker_url"))
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_URL"))
        )
        if not url:
            raise ProviderError("connection_missing", "远端 GPU Worker 连接地址缺失")
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderError("connection_missing", "远端 GPU Worker 连接地址格式无效")
        token = (
            _clean_str(conn.get("api_key"))
            or _clean_str(conn.get("remote_worker_token"))
            or _clean_str(ctx.get("remote_worker_token"))
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_TOKEN"))
            or _clean_str(os.environ.get("ASMR_WORKER_TOKEN"))
        )
        raw_timeout = (
            conn.get("remote_worker_timeout")
            or ctx.get("remote_worker_timeout")
            or conn.get("timeout")
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_TIMEOUT"))
        )
        timeout = float(raw_timeout) if raw_timeout is not None else 600.0
        transport = (
            ctx.get("remote_transport")
            or conn.get("remote_transport")
            or getattr(self, "_remote_transport", None)
        )
        return url.rstrip("/"), token, timeout, transport

    @staticmethod
    def _map_compute_error_payload(
        code: str,
        message: str,
        *,
        retryable: bool = False,
        token: str | None = None,
    ) -> ProviderError:
        from packages.protocol.errors import ComputeErrorCode

        safe_msg = _redact_secret(str(message or "未知远端错误"), token)
        if code in {ComputeErrorCode.AUTH_REQUIRED, ComputeErrorCode.AUTH_INVALID}:
            return ProviderError("authentication_failed", f"远端 GPU Worker 认证失败：{safe_msg}")
        if code == ComputeErrorCode.TIMEOUT:
            return ProviderError(
                "remote_timeout",
                f"远端 GPU Worker 响应超时：{safe_msg}",
                retryable=True,
                result_unknown=True,
            )
        if code == ComputeErrorCode.TRANSPORT_ERROR:
            return ProviderError(
                "connection_failed",
                f"远端 GPU Worker 连接失败：{safe_msg}",
                retryable=True,
                result_unknown=True,
            )
        if code == ComputeErrorCode.MODEL_NOT_AVAILABLE:
            return ProviderError("model_unavailable", f"远端 GPU Worker 模型不可用：{safe_msg}")
        if code == ComputeErrorCode.OOM_ERROR:
            return ProviderError(
                "remote_oom", f"远端 GPU Worker 显存不足：{safe_msg}", retryable=True
            )
        if code == ComputeErrorCode.LEASE_CONFLICT:
            return ProviderError(
                "remote_busy", f"远端 GPU Worker 繁忙：{safe_msg}", retryable=True
            )
        if code == ComputeErrorCode.AUDIO_DECODE_ERROR:
            return ProviderError("invalid_audio", f"远端 GPU Worker 音频编解码失败：{safe_msg}")
        return ProviderError(
            "remote_failed",
            f"远端 GPU Worker 推理失败：{safe_msg}",
            retryable=bool(retryable),
        )

    def _probe_remote_worker(self, context: dict) -> dict[str, Any]:
        from packages.gpu_worker.client import ComputeClient, RemoteHttpTransport
        from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

        model = context.get("model")
        mode = context.get("mode")
        if mode is not None:
            mode_desc = next((m for m in self.modes if m["id"] == mode), None)
            if mode_desc is None:
                return {
                    "ready": False,
                    "reachable": None,
                    "verified": False,
                    "code": "invalid_mode",
                    "detail": "未知引擎模式",
                }
            if model is not None and mode_desc["models"] and model not in mode_desc["models"]:
                return {
                    "ready": False,
                    "reachable": None,
                    "verified": False,
                    "code": "model_mismatch",
                    "detail": "模型与所选模式不匹配",
                }

        try:
            url, token, timeout, transport = self._resolve_remote_worker_config(context)
        except ProviderError as exc:
            return {
                "ready": False,
                "reachable": False,
                "verified": False,
                "code": exc.code,
                "detail": str(exc),
            }

        try:
            with ComputeClient(
                RemoteHttpTransport(
                    base_url=url,
                    api_key=token,
                    timeout=min(timeout, 30.0),
                    transport=transport,
                )
            ) as client:
                caps = client.capabilities()
        except ComputeRemoteError as exc:
            mapped = self._map_compute_error_payload(
                exc.code, exc.payload.message, retryable=exc.retryable, token=token
            )
            reachable = exc.code in {ComputeErrorCode.AUTH_REQUIRED, ComputeErrorCode.AUTH_INVALID}
            return {
                "ready": False,
                "reachable": reachable,
                "verified": False,
                "code": mapped.code,
                "detail": str(mapped),
            }

        if "tts_batch" not in caps.supported_tasks:
            return {
                "ready": False,
                "reachable": True,
                "verified": False,
                "code": "model_unavailable",
                "detail": "远端 GPU Worker 不支持 tts_batch 任务",
            }
        return {
            "ready": True,
            "reachable": True,
            "verified": True,
            "remote_worker_url": url,
            "device": caps.device,
            "cuda_available": caps.cuda_available,
            "vram_total_mb": caps.vram_total_mb,
            "protocol_version": caps.protocol_version,
            "detail": f"远端 GPU Worker 已就绪（{caps.device}）",
        }

    def probe(self, context):
        """Readiness only: no generation, downloads, reference uploads or model loading."""
        if self.http:
            conn = context.get("connection", {})
            ready = bool(conn.get("base_url") and conn.get("api_key"))
            return {"ready": ready, "reachable": None, "verified": False, "detail": "连接已配置，尚未验证服务可达性" if ready else "连接配置不完整"}
        if self.provider_id == "edge":
            from importlib.util import find_spec
            ready = find_spec("edge_tts") is not None
            return {"ready": ready, "reachable": None, "verified": False}
        if self._has_remote_worker(context):
            return self._probe_remote_worker(context)
        try:
            runtime, model_path, _ = self._local_settings(context.get("model"), context.get("mode"), context)
            return {"ready": True, "reachable": None, "verified": False,
                "model_path": model_path, "runtime": str(runtime), "detail": "模型与运行环境存在；尚未执行合成"}
        except ProviderError as exc:
            return {"ready": False, "reachable": None, "verified": False, "code": exc.code, "detail": str(exc)}

    def _local_settings(self, model, mode, context):
        from src.core.runtime.profiles import get_runtime_profile_resolver
        from src.core.resources.model_reference import resolve_model_reference
        resolver = get_runtime_profile_resolver()
        runtime = context.get("runtime") or ("qwen_tts" if self.provider_id == "qwen3" else "voxcpm2")
        candidate = Path(runtime)
        if candidate.is_absolute():
            executable = candidate if candidate.is_file() else candidate / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
        else:
            try:
                executable = resolver.resolve(runtime).python_executable
            except Exception:
                raise ProviderError("runtime_missing", "未知本地引擎运行环境") from None
        if not executable.is_file():
            raise ProviderError("runtime_missing", "本地引擎运行环境未安装")
        if not model:
            raise ProviderError("model_missing", "请先选择模型与模式后检测")
        model_path = str(context.get("model_path") or resolve_model_reference(model))
        config_path = Path(model_path) / "config.json"
        if not config_path.is_file():
            raise ProviderError("model_missing", "请先安装指定本地模型")
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            raise ProviderError("model_invalid", "本地模型配置无法读取") from None
        if self.provider_id == "qwen3":
            expected = {"builtin": "custom_voice", "reference": "base", "design": "voice_design"}.get(mode)
            if not expected or config.get("tts_model_type") != expected:
                raise ProviderError("model_mismatch", "Qwen 模型目录与所选模式不符")
        elif config.get("architecture") != "voxcpm2":
            raise ProviderError("model_mismatch", "模型目录不是 VoxCPM2")
        weights = Path(model_path) / "model.safetensors"
        index = Path(model_path) / "model.safetensors.index.json"
        if not weights.is_file() and not index.is_file():
            raise ProviderError("model_missing", "本地模型权重尚未安装完整")
        return executable, model_path, resolver

    def synthesize(self, request, output_path: Path, context: dict, cancel_check):
        _cancel(cancel_check)
        if request.get("provider_id") != self.provider_id or request.get("provider_version") != self.version:
            raise ProviderError("version_mismatch", "引擎版本与编译快照不符")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.http:
            remote_id = self._remote(request, output_path, context)
        elif self.provider_id == "edge":
            from src.core.tts import EdgeTTSEngine
            p = request["parameters"]
            speed = p["options"]["speed"]
            raw_proxy = (
                context.get("connection", {}).get("proxy")
                or os.environ.get("HTTPS_PROXY")
                or os.environ.get("HTTP_PROXY")
            )
            proxy = (
                raw_proxy.strip()
                if isinstance(raw_proxy, str) and raw_proxy.strip().lower().startswith(("http://", "https://"))
                else None
            )
            edge_kwargs = {"voice": p["variant"]["value"], "rate": f"{round((speed - 1) * 100):+d}%"}
            if proxy:
                edge_kwargs["proxy"] = proxy
            try:
                EdgeTTSEngine(**edge_kwargs).synthesize(request["text"], str(output_path))
            except RuntimeError as exc:
                detail = (
                    "Edge 在线语音握手被拒绝（HTTP 403）或网络受限，请检查系统网络/HTTP 代理或改用本地/云端音色"
                    if "WSServerHandshakeError" in str(exc) or "403" in str(exc)
                    else f"Edge 在线语音请求失败：{exc}"
                )
                raise ProviderError("remote_failed", detail, retryable=True) from None
            remote_id = None
        elif self._has_remote_worker(context) or context.get("_remote_session") is not None:
            self._remote_gpu(request, output_path, context, cancel_check)
            remote_id = None
        else:
            while not _LOCAL_LOCK.acquire(timeout=.2):
                _cancel(cancel_check)
            try:
                _cancel(cancel_check)
                self._local(request, output_path, context, cancel_check)
            finally:
                _LOCAL_LOCK.release()
            remote_id = None
        _cancel(cancel_check)
        try:
            info = sf.info(output_path)
            samples, _ = sf.read(output_path, dtype="float32")
            if info.frames <= 0 or not np.isfinite(samples).all():
                raise ValueError("empty")
        except Exception:
            raise ProviderError("invalid_audio", "引擎输出无法解码为完整音频") from None
        return {"path": str(output_path), "container": info.format, "codec": info.subtype,
            "sample_rate": info.samplerate, "channels": info.channels, "duration": info.duration,
            "model": request["model"], "provider_id": self.provider_id, "remote_request_id": remote_id}

    def _remote(self, request, output_path, context):
        connection = context.get("connection", {})
        base, key = str(connection.get("base_url", "")).rstrip("/"), connection.get("api_key")
        parsed = urlsplit(base)
        if not key or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
            raise ProviderError("connection_missing", "外部连接地址或凭据缺失")
        if connection.get("provider_id", self.provider_id) != self.provider_id:
            raise ProviderError("connection_mismatch", "连接协议与引擎不符")
        p = request["parameters"]
        headers = {"Authorization": f"Bearer {key}"}
        if self.provider_id == "fish_audio":
            endpoint = "/tts"
            # Accept the official origin as well as the documented /v1 base.
            # Custom proxy prefixes remain explicit and are never rewritten.
            if parsed.hostname == "api.fish.audio" and parsed.path in {"", "/"}:
                base += "/v1"
            headers["model"] = request["model"]
            body = {"text": p["rendered_text"], "reference_id": p["variant"]["value"], "format": "wav",
                "temperature": p["options"]["temperature"], "top_p": p["options"]["top_p"]}
            if p["options"]["speed"] != 1:
                body["prosody"] = {"speed": p["options"]["speed"]}
        else:
            endpoint = "/audio/speech"
            body = {"model": request["model"], "input": request["text"], "voice": p["variant"]["value"],
                "response_format": "wav", "speed": p["options"]["speed"]}
        return self._http_audio(base if parsed.path.endswith(endpoint) else base + endpoint, headers, body, output_path, connection)

    @staticmethod
    def _http_audio(url, headers, body, output_path, connection):
        try:
            with httpx.Client(timeout=httpx.Timeout(float(connection.get("timeout", 180)), connect=15)) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise ProviderError("result_unknown", "远端响应超时，请确认计费与结果后再生成", result_unknown=True) from None
        except httpx.RequestError:
            raise ProviderError("connection_failed", "外部语音服务连接失败", result_unknown=True) from None
        if response.status_code in {401, 403}:
            raise ProviderError("authentication_failed", "外部语音服务认证失败")
        if response.status_code == 402:
            raise ProviderError("payment_required", "外部语音服务余额不足或需要付费，请检查账户计费状态后再试")
        if response.status_code == 429:
            raise ProviderError("rate_limited", "外部语音服务请求限流")
        if response.status_code == 404:
            raise ProviderError("model_unavailable", "服务端点、模型或音色不可用")
        if not response.is_success:
            raise ProviderError("remote_failed", f"外部语音服务失败（HTTP {response.status_code}）", result_unknown=response.status_code >= 500)
        try:
            content = response.content
            audio, rate = sf.read(BytesIO(content), dtype="float32")
            if len(audio) == 0 or not np.isfinite(audio).all():
                raise ValueError("empty")
            sf.write(output_path, audio, rate)
        except Exception:
            raise ProviderError("invalid_audio", "远端没有返回可解码音频") from None
        return response.headers.get("x-request-id") or response.headers.get("request-id")

    def _verify_invocation_assets_and_params(
        self,
        request: dict,
        context: dict,
        *,
        verified_assets: dict[str, str] | None = None,
        default_device: str,
    ) -> tuple[dict[str, str], dict, str, str]:
        references: dict[str, str] = {}
        for aid, digest in request["asset_hashes"].items():
            if verified_assets is not None and aid in verified_assets:
                resolved_path = Path(verified_assets[aid])
                if resolved_path.is_file():
                    references[aid] = verified_assets[aid]
                    continue
            asset = context.get("assets", {}).get(aid, {})
            path = Path(asset.get("path", ""))
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ProviderError("asset_changed", "参考素材缺失或已被修改")
            resolved_str = str(path.resolve())
            references[aid] = resolved_str
            if verified_assets is not None:
                verified_assets[aid] = resolved_str
        request = deepcopy(request)
        # Old frozen requests may contain a device; new reusable options never do.
        device = context.get("device") or request["parameters"]["options"].get("device") or default_device
        if device not in {"auto", "cpu", "cuda:0"}:
            raise ProviderError("invalid_device", "不支持的本地设备")
        precision = context.get("precision") or "auto"
        if precision not in {"auto", "float32", "float16", "bfloat16"}:
            raise ProviderError("invalid_precision", "不支持的模型精度")
        if self.provider_id == "voxcpm2" and precision != "auto":
            raise ProviderError("unsupported_precision", "VoxCPM2 当前使用模型默认精度，请选择 auto")
        return references, request, device, precision

    def _resolve_local_invocation(self, request, context, verified_assets: dict[str, str] | None = None):
        executable, model_path, resolver = self._local_settings(request["model"], request["mode"], context)
        references, request, device, precision = self._verify_invocation_assets_and_params(
            request,
            context,
            verified_assets=verified_assets,
            default_device="cuda:0" if self.provider_id == "qwen3" else "auto",
        )
        return executable, model_path, resolver, references, request, device, precision

    @staticmethod
    def _compute_tts_item(req, idx=0, output_path=None):
        from packages.protocol.compute import TtsSynthesizeItem

        params = req["parameters"]
        variant = params["variant"]
        raw_kind = variant["kind"]
        proto_kind = "preset" if raw_kind == "builtin" else raw_kind
        speaker = variant["value"] if raw_kind == "builtin" else None
        ref_id = variant["value"] if raw_kind == "reference" else None
        item_opts = {
            k: v
            for k, v in params["options"].items()
            if k not in {"schema_version", "device"}
        }
        return TtsSynthesizeItem(
            item_id=f"item-{idx}",
            text=req["text"],
            output_path=output_path,
            language=params.get("language", "auto"),
            speaker=speaker,
            instruction=params.get("instruction", ""),
            variant_kind=proto_kind,
            variant_value=variant["value"],
            reference_id=ref_id,
            reference_transcript=params.get("reference_transcript", ""),
            options=item_opts,
        )

    def _local_job(self, request, references, model_path, device, precision, output_path, response_path):
        from packages.protocol.compute import TtsBatchRequest

        item = self._compute_tts_item(request, output_path=str(output_path.resolve()))
        batch = TtsBatchRequest(provider_id=self.provider_id, model=str(model_path), device=device,
                                precision=precision, output_format="wav", items=[item], references=references)
        return {"task": "tts_batch", "request": batch.model_dump(), "response_path": str(response_path)}

    @staticmethod
    def _check_local_result(response_path):
        envelope = json.loads(response_path.read_text(encoding="utf-8"))
        items = envelope.get("result", {}).get("items", [])
        if not envelope.get("ok") or len(items) != 1 or not items[0].get("ok"):
            error = (items[0].get("error") if items else None) or envelope.get("error") or {}
            raise ProviderError("local_failed", error.get("message") or "本地语音推理失败")

    def _build_remote_tts_batch_request(
        self,
        requests: list[dict],
        context: dict,
        *,
        verified_assets: dict[str, str] | None = None,
    ):
        from packages.protocol.compute import TtsBatchRequest

        all_references: dict[str, str] = {}
        items = []
        batch_model = ""
        batch_device = "auto"
        batch_precision = "auto"
        asset_cache = verified_assets if verified_assets is not None else {}

        for idx, raw_req in enumerate(requests):
            if (
                raw_req.get("provider_id") != self.provider_id
                or raw_req.get("provider_version") != self.version
            ):
                raise ProviderError("version_mismatch", "引擎版本与编译快照不符")
            refs, req, device, precision = self._verify_invocation_assets_and_params(
                raw_req,
                context,
                verified_assets=asset_cache,
                default_device="auto",
            )
            all_references.update(refs)
            if idx == 0:
                batch_model = str(req["model"])
                batch_device = device
                batch_precision = precision

            items.append(self._compute_tts_item(req, idx))

        if len(all_references) == 1:
            primary_ref = next(iter(all_references.values()))
            ref_map: dict[str, str] = {}
        else:
            primary_ref = None
            ref_map = dict(all_references)

        return TtsBatchRequest(
            provider_id=self.provider_id,
            model=batch_model,
            device=batch_device,
            precision=batch_precision,
            output_format="flac",
            items=items,
            reference_audio_path=primary_ref,
            references=ref_map,
            options=dict(items[0].options) if items else {},
        )

    def _materialize_remote_tts_item(
        self,
        item_res,
        output_path: Path,
        *,
        token: str | None = None,
    ) -> None:
        from packages.gpu_worker.handlers import materialize_audio_bytes_to_path
        from packages.protocol.errors import ComputeRemoteError

        if not item_res.ok:
            if item_res.error is not None:
                raise self._map_compute_error_payload(
                    item_res.error.code,
                    item_res.error.message,
                    retryable=item_res.error.retryable,
                    token=token,
                )
            raise ProviderError("remote_failed", "远端 GPU Worker 单句语音合成失败")

        if not item_res.audio_b64:
            raise ProviderError("invalid_audio", "远端 GPU Worker 未返回可解码音频数据")

        try:
            audio_raw = base64.b64decode(item_res.audio_b64, validate=True)
            materialize_audio_bytes_to_path(
                audio_raw,
                output_path,
                stage="tts_batch",
                wav_subtype="FLOAT",
            )
        except ComputeRemoteError as exc:
            raise self._map_compute_error_payload(
                exc.code, exc.payload.message, retryable=exc.retryable, token=token
            ) from None
        except Exception:
            raise ProviderError("invalid_audio", "远端 GPU Worker 返回的音频无法解码") from None

    def _remote_gpu(self, request: dict, output_path: Path, context: dict, cancel_check) -> None:
        session = context.get("_remote_session")
        if session is not None:
            session.run(request, output_path, context, cancel_check)
            return

        from packages.gpu_worker.client import ComputeClient, RemoteHttpTransport
        from packages.protocol.errors import ComputeRemoteError

        _cancel(cancel_check)
        url, token, timeout, transport = self._resolve_remote_worker_config(context)
        batch_req = self._build_remote_tts_batch_request([request], context)
        _cancel(cancel_check)

        try:
            with ComputeClient(
                RemoteHttpTransport(
                    base_url=url,
                    api_key=token,
                    timeout=timeout,
                    transport=transport,
                )
            ) as client:
                result = client.tts_batch(batch_req)
        except ComputeRemoteError as exc:
            raise self._map_compute_error_payload(
                exc.code, exc.payload.message, retryable=exc.retryable, token=token
            ) from None

        if not result.items:
            raise ProviderError("remote_failed", "远端 GPU Worker 未返回合成结果")
        self._materialize_remote_tts_item(result.items[0], output_path, token=token)

    @contextmanager
    def batch_session(self, requests, context: dict):
        if self.remote or self.provider_id not in {"qwen3", "voxcpm2"} or len(requests) <= 1:
            yield context
            return
        if self._has_remote_worker(context):
            remote_session = _RemoteBatchSession(self, requests)
            scoped_context = dict(context)
            scoped_context["_remote_session"] = remote_session
            try:
                yield scoped_context
            finally:
                remote_session.close()
            return
        session = _LocalBatchSession(self)
        scoped_context = dict(context)
        scoped_context["_local_session"] = session
        try:
            yield scoped_context
        finally:
            session.close()

    def _local(self, request, output_path, context, cancel_check):
        session = context.get("_local_session")
        if session is not None:
            session.run(request, output_path, context, cancel_check)
            return
        from src.config import PROJECT_ROOT
        executable, model_path, resolver, references, request, device, precision = self._resolve_local_invocation(
            request, context
        )
        from src.workspace_paths import temporary_directory
        temp_root = temporary_directory()
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="speech-worker-", dir=temp_root) as directory:
            input_path = Path(directory) / "request.json"
            response_path = Path(directory) / "response.json"
            job = self._local_job(request, references, model_path, device, precision, output_path, response_path)
            input_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            with (Path(directory) / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([str(executable), "-m", "packages.gpu_worker.cli", "--once", str(input_path)],
                    cwd=str(PROJECT_ROOT), env=resolver.subprocess_env(), stdout=log, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic() + 1800
                    while process.poll() is None:
                        _cancel(cancel_check)
                        if time.monotonic() > deadline:
                            raise ProviderError("local_timeout", "本地模型执行超时")
                        time.sleep(.1)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            if process.returncode != 0 or not response_path.is_file():
                raise ProviderError("local_failed", "本地语音推理失败，请检查模型、设备与参考素材")

            self._check_local_result(response_path)

    def release(self):
        # Single-shot local workers exit immediately; batch sessions clean up via batch_session().
        return None


class _RemoteBatchSession:
    """Execute multi-cue batch synthesis in a single `/v1/tts/batch` RPC over `ComputeClient`."""

    def __init__(self, provider: SpeechProvider, planned_requests: list[dict]) -> None:
        self._provider = provider
        self._planned_requests = [deepcopy(req) for req in planned_requests]
        self._verified_assets: dict[str, str] = {}
        self._client = None
        self._token: str | None = None
        self._batch_results: dict[str, Any] | None = None
        self._cursor = 0

    @staticmethod
    def _matches_planned(planned: dict, actual: dict) -> bool:
        return all(
            planned.get(key) == actual.get(key)
            for key in (
                "provider_id",
                "provider_version",
                "model",
                "mode",
                "segment_id",
                "text",
                "parameters",
                "asset_hashes",
            )
        )

    def _ensure_client(self, context: dict):
        if self._client is None:
            from packages.gpu_worker.client import ComputeClient, RemoteHttpTransport

            url, token, timeout, transport = self._provider._resolve_remote_worker_config(context)
            self._token = token
            self._client = ComputeClient(
                RemoteHttpTransport(
                    base_url=url,
                    api_key=token,
                    timeout=timeout,
                    transport=transport,
                )
            )
        return self._client

    def run(self, request: dict, output_path: Path, context: dict, cancel_check) -> None:
        from packages.protocol.errors import ComputeRemoteError

        _cancel(cancel_check)
        client = self._ensure_client(context)

        if (
            self._batch_results is None
            and not context.get("checkpoint_each_take")
            and self._cursor == 0
            and self._planned_requests
            and self._matches_planned(self._planned_requests[0], request)
            and len({req.get("model") for req in self._planned_requests}) == 1
        ):
            batch_req = self._provider._build_remote_tts_batch_request(
                self._planned_requests,
                context,
                verified_assets=self._verified_assets,
            )
            _cancel(cancel_check)
            try:
                res = client.tts_batch(batch_req)
            except ComputeRemoteError as exc:
                raise self._provider._map_compute_error_payload(
                    exc.code, exc.payload.message, retryable=exc.retryable, token=self._token
                ) from None
            self._batch_results = {item.item_id: item for item in res.items}

        if (
            self._batch_results is not None
            and self._cursor < len(self._planned_requests)
            and self._matches_planned(self._planned_requests[self._cursor], request)
        ):
            item_id = f"item-{self._cursor}"
            self._cursor += 1
            item_res = self._batch_results.get(item_id)
            if item_res is None:
                raise ProviderError("remote_failed", f"远端 GPU Worker 缺少批次条目结果：{item_id}")
            self._provider._materialize_remote_tts_item(
                item_res, output_path, token=self._token
            )
            return

        single_req = self._provider._build_remote_tts_batch_request(
            [request],
            context,
            verified_assets=self._verified_assets,
        )
        _cancel(cancel_check)
        try:
            single_res = client.tts_batch(single_req)
        except ComputeRemoteError as exc:
            raise self._provider._map_compute_error_payload(
                exc.code, exc.payload.message, retryable=exc.retryable, token=self._token
            ) from None
        if not single_res.items:
            raise ProviderError("remote_failed", "远端 GPU Worker 未返回合成结果")
        self._provider._materialize_remote_tts_item(
            single_res.items[0], output_path, token=self._token
        )

    def close(self) -> None:
        client, self._client = self._client, None
        self._batch_results = None
        if client is not None:
            client.close()


class _LocalBatchSession:
    """Keep one isolated gpu-worker warm across a multi-cue batch."""

    def __init__(self, provider: SpeechProvider) -> None:
        self._provider = provider
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._log_handle = None
        self._process: subprocess.Popen | None = None
        self._key: tuple | None = None
        self._job_counter = 0
        self._verified_assets: dict[str, str] = {}

    def _ensure_started(self, executable, model_path, resolver, device, precision, cancel_check) -> Path:
        key = (str(executable), str(model_path), device, precision)
        if self._process is not None and self._process.poll() is None and self._key == key and self._temp_dir is not None:
            return Path(self._temp_dir.name)
        self.close()
        from src.config import PROJECT_ROOT
        from src.workspace_paths import temporary_directory

        temp_root = temporary_directory()
        temp_root.mkdir(parents=True, exist_ok=True)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="speech-batch-worker-", dir=temp_root)
        directory = Path(self._temp_dir.name)
        ready_path = directory / "ready.json"
        self._log_handle = (directory / "worker.log").open("w", encoding="utf-8")
        self._process = subprocess.Popen(
            [str(executable), "-m", "packages.gpu_worker.cli", "--session", str(ready_path)],
            cwd=str(PROJECT_ROOT),
            env=resolver.subprocess_env(),
            stdin=subprocess.PIPE,
            stdout=self._log_handle,
            stderr=self._log_handle,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._key = key
        deadline = time.monotonic() + 1800
        try:
            while not ready_path.is_file():
                if self._process.poll() is not None:
                    raise ProviderError("local_failed", "本地语音模型加载失败，请检查模型、设备与显存")
                _cancel(cancel_check)
                if time.monotonic() > deadline:
                    raise ProviderError("local_timeout", "本地模型加载超时")
                time.sleep(0.05)
        except BaseException:
            self.close()
            raise
        return directory

    def run(self, request, output_path: Path, context: dict, cancel_check) -> None:
        executable, model_path, resolver, references, request, device, precision = self._provider._resolve_local_invocation(
            request, context, verified_assets=self._verified_assets
        )
        directory = self._ensure_started(
            executable, model_path, resolver, device, precision, cancel_check
        )
        assert self._process is not None and self._process.stdin is not None
        self._job_counter += 1
        job_path = directory / f"job-{self._job_counter}.json"
        response_path = directory / f"response-{self._job_counter}.json"
        job = self._provider._local_job(request, references, model_path, device, precision, output_path, response_path)
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        try:
            self._process.stdin.write(f"{job_path}\n")
            self._process.stdin.flush()
            deadline = time.monotonic() + 1800
            while not response_path.is_file():
                if self._process.poll() is not None:
                    raise ProviderError("local_failed", "本地语音推理进程异常退出，请检查模型、设备与参考素材")
                _cancel(cancel_check)
                if time.monotonic() > deadline:
                    raise ProviderError("local_timeout", "本地模型执行超时")
                time.sleep(0.05)
            self._provider._check_local_result(response_path)
        except BaseException:
            if self._process is not None and self._process.poll() is None:
                self.close()
            raise
        finally:
            job_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)

    def close(self) -> None:
        proc, self._process = self._process, None
        self._key = None
        if proc is not None:
            if proc.stdin is not None:
                try:
                    if proc.poll() is None:
                        proc.stdin.write("STOP\n")
                        proc.stdin.flush()
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            except OSError:
                pass
            self._temp_dir = None


_PROVIDERS = {name: SpeechProvider(name) for name in SCHEMAS}
_CLOUD_REGISTERED = False
_CLOUD_LOCK = threading.Lock()


def _ensure_cloud_providers():
    # Lazy registration also allows adapters to import the base contract without
    # creating a circular import when a focused test imports an adapter first.
    global _CLOUD_REGISTERED
    if _CLOUD_REGISTERED:
        return
    with _CLOUD_LOCK:
        if _CLOUD_REGISTERED:
            return
        from .cloud_gemini import GeminiSpeechProvider
        from .cloud_elevenlabs import ElevenLabsSpeechProvider
        from .cloud_mimo import MimoSpeechProvider
        for provider in (GeminiSpeechProvider(), ElevenLabsSpeechProvider(), MimoSpeechProvider()):
            register_provider(provider)
        _CLOUD_REGISTERED = True


def register_provider(provider):
    if provider.provider_id in _PROVIDERS:
        raise ProviderError("duplicate_provider", "引擎已注册")
    _PROVIDERS[provider.provider_id] = provider


def get_provider(provider_id):
    _ensure_cloud_providers()
    try:
        return _PROVIDERS[provider_id]
    except (KeyError, TypeError):
        raise ProviderError("unknown_provider", "未注册的语音引擎") from None


def list_providers():
    _ensure_cloud_providers()
    return [provider.describe() for provider in _PROVIDERS.values()]
