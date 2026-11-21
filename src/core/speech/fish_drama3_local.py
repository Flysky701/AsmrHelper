"""Same-host SGLang-Omni integration for the official Fish Audio Drama 3 model."""
from __future__ import annotations

import base64
from urllib.parse import urlsplit

import httpx

from .cloud_http import join_endpoint, post_audio, reference_audio
from .providers import COMMON, ProviderError, SpeechProvider


class FishDrama3LocalSpeechProvider(SpeechProvider):
    provider_id = "fish_audio_local"
    name = "Fish Audio Drama 3 · 本机 SGLang-Omni"
    model_id = "fish_drama3"
    default_base_url = "http://127.0.0.1:18083/v1"
    remote = False
    http = True
    connection_required = False
    options_schema = {
        **COMMON,
        "style_description": {"type": "string", "maxLength": 300, "default": ""},
    }
    modes = [
        {"id": mode, "variant_kinds": [mode], "models": ["fish_drama3"]}
        for mode in ("default", "reference")
    ]

    def __init__(self):
        # This adapter defines its own contract instead of using the built-in tables.
        pass

    def voice_sources(self, mode):
        info = super().voice_sources(mode)
        if mode == "default":
            info.update(default="default", required=False)
        return info

    def capabilities(self, model=None, mode=None):
        caps = super().capabilities(model, mode)
        for delivery in caps["delivery"].values():
            delivery.update(support="direct", evidence="unverified")
        caps["emotion"] = {"support": "direct", "evidence": "unverified"}
        caps["cancellation"] = "between_segments"
        if mode == "reference":
            caps["reference"].update(transcript_required=True, duration_limit_seconds=60)
        return caps

    def runtime_options(self, model, mode):
        return ["style_description"] if model == self.model_id and mode in {"default", "reference"} else []

    def reference_requires_transcript(self, recipe):
        return recipe.get("mode") == "reference"

    def compile(self, recipe, segment, text, assets):
        params = super().compile(recipe, segment, text, assets)
        cues = []
        if params["delivery"] != "normal":
            cues.append({"whisper": "whispering", "soft": "soft tone"}[params["delivery"]])
        if params["emotion"] != "neutral":
            cues.append(params["emotion"])
        description = params["options"]["style_description"].strip()
        if any(char in description for char in "[]\r\n"):
            raise ProviderError("invalid_options", "风格描述不能含标签边界或换行")
        if description:
            cues.append(description)
        params["rendered_text"] = "".join(f"[{cue}]" for cue in cues) + text
        if recipe["mode"] == "reference":
            params["reference_transcript"] = assets[params["variant"]["value"]]["transcript"]
        return params

    def connection_base(self, connection):
        if connection.get("deployment", "local") != "local" or connection.get("provider_id", self.provider_id) != self.provider_id:
            raise ProviderError("connection_mismatch", "请选择本机 Drama 3 连接")
        raw = str(connection.get("base_url") or self.default_base_url).strip()
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError:
            raise ProviderError("connection_missing", "本机 Drama 3 地址无效") from None
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") not in {"", "/v1", "/v1/audio/speech"}):
            raise ProviderError("connection_missing", "本机 Drama 3 仅接受回环地址与 /v1 基础路径")
        # Use a literal loopback even when the configured hostname is localhost.
        host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
        return f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}/v1"

    @staticmethod
    def _headers(connection):
        key = connection.get("api_key")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def _check_service(self, base, headers):
        try:
            with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
                response = client.get(join_endpoint(base, "/v1/models"), headers=headers)
            if response.status_code in {401, 403}:
                raise ProviderError("authentication_failed", "本机 Drama 3 服务认证失败")
            response.raise_for_status()
            models = response.json()["data"]
        except httpx.RequestError:
            raise ProviderError("runtime_missing", "未连接本机 Drama 3。请在 Linux 或 WSL2 启动 SGLang-Omni 服务") from None
        except (httpx.HTTPStatusError, ValueError, KeyError, TypeError):
            raise ProviderError("model_unavailable", "本机端点未返回 SGLang-Omni 模型列表") from None
        if not isinstance(models, list) or not any(
            isinstance(model, dict) and model.get("id") == self.model_id for model in models
        ):
            raise ProviderError("model_mismatch", "本机服务未提供 fish_drama3，请用 --model-name fish_drama3 启动")

    def probe(self, context):
        connection = context.get("connection", {})
        try:
            base = self.connection_base(connection)
            self._check_service(base, self._headers(connection))
        except ProviderError as exc:
            return {"ready": False, "verified": False, "reachable": None, "code": exc.code, "detail": str(exc)}
        return {"ready": True, "verified": False, "reachable": True,
                "detail": "本机 SGLang-Omni 已报告 fish_drama3；尚未执行合成"}

    def _remote(self, request, output_path, context):
        connection = context.get("connection", {})
        base = self.connection_base(connection)
        headers = self._headers(connection)
        params = request["parameters"]
        recipe = {"model": request["model"], "mode": request["mode"], "variant": params["variant"],
                  "language": params["language"], "provider_options": params["options"]}
        if params != self.compile(recipe, params, request["text"], context.get("assets", {})):
            raise ProviderError("invalid_snapshot", "Drama 3 编译参数与语音请求不匹配")
        body = {"model": self.model_id, "input": params["rendered_text"], "response_format": "wav", "stream": False}
        if recipe["mode"] == "reference":
            raw, _ = reference_audio(request, context)
            body["references"] = [
                {"data": base64.b64encode(raw).decode("ascii"), "text": params["reference_transcript"]}
            ]
        self._check_service(base, headers)
        return post_audio(join_endpoint(base, "/v1/audio/speech"), headers, body, output_path,
                          connection, local=True)
