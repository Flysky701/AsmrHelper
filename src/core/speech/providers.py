"""Explicit speech provider contracts; no voice-profile or configuration fallback."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import threading
import time
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
        return deepcopy({"provider_id": self.provider_id, "name": {"fish_audio": "Fish Audio", "edge": "Edge TTS",
            "qwen3": "Qwen3 TTS", "voxcpm2": "VoxCPM2", "openai_compatible": "OpenAI 兼容语音"}.get(self.provider_id, getattr(self, "name", self.provider_id)),
            "version": self.version, "contract_version": 1, "remote": self.remote,
            "connection_required": self.http,
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
            EdgeTTSEngine(voice=p["variant"]["value"], rate=f"{round((speed - 1) * 100):+d}%").synthesize(request["text"], str(output_path))
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

    def _local(self, request, output_path, context, cancel_check):
        from src.config import PROJECT_ROOT
        executable, model_path, resolver = self._local_settings(request["model"], request["mode"], context)
        references = {}
        for aid, digest in request["asset_hashes"].items():
            asset = context.get("assets", {}).get(aid, {})
            path = Path(asset.get("path", ""))
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ProviderError("asset_changed", "参考素材缺失或已被修改")
            references[aid] = str(path.resolve())
        request = deepcopy(request)
        # Old frozen requests may contain a device; new reusable options never do.
        device = context.get("device") or request["parameters"]["options"].get("device") or ("cuda:0" if self.provider_id == "qwen3" else "auto")
        if device not in {"auto", "cpu", "cuda:0"}:
            raise ProviderError("invalid_device", "不支持的本地设备")
        precision = context.get("precision") or "auto"
        if precision not in {"auto", "float32", "float16", "bfloat16"}:
            raise ProviderError("invalid_precision", "不支持的模型精度")
        if self.provider_id == "voxcpm2" and precision != "auto":
            raise ProviderError("unsupported_precision", "VoxCPM2 当前使用模型默认精度，请选择 auto")
        from src.workspace_paths import temporary_directory
        temp_root = temporary_directory()
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="speech-worker-", dir=temp_root) as directory:
            input_path = Path(directory) / "request.json"
            response_path = Path(directory) / "response.json"
            input_path.write_text(json.dumps({"request": request, "references": references, "model_path": model_path,
                "precision": precision, "device": device, "output_path": str(output_path.resolve()), "response_path": str(response_path)}, ensure_ascii=False), encoding="utf-8")
            with (Path(directory) / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([str(executable), "-m", "src.core.speech.local_worker", str(input_path)],
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

    def release(self):
        # Local workers are scoped to one synthesis; remote clients are context-managed.
        return None


_PROVIDERS = {name: SpeechProvider(name) for name in SCHEMAS}


def register_provider(provider):
    if provider.provider_id in _PROVIDERS:
        raise ProviderError("duplicate_provider", "引擎已注册")
    _PROVIDERS[provider.provider_id] = provider


def get_provider(provider_id):
    try:
        return _PROVIDERS[provider_id]
    except (KeyError, TypeError):
        raise ProviderError("unknown_provider", "未注册的语音引擎") from None


def list_providers():
    return [provider.describe() for provider in _PROVIDERS.values()]
