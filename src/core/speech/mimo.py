"""MiMo's explicit chat-audio protocol, independent of OpenAI speech endpoints."""
from urllib.parse import urlsplit

from .providers import COMMON, ProviderError, SpeechProvider, STYLE_TEXT


class MimoProvider(SpeechProvider):
    provider_id, version, name = "mimo_audio", "1", "MiMo 语音"
    remote, http = True, True

    def __init__(self):
        self.options_schema = {**COMMON, "instructions": {"type": "string", "maxLength": 2000, "default": ""}}
        self.modes = [{"id": "hosted", "variant_kinds": ["hosted"], "models": ["mimo-v2.5-tts"]}]

    def capabilities(self, model=None, mode=None):
        caps = super().capabilities(model, mode)
        for value in caps["delivery"].values():
            value["support"] = "direct"
        caps["emotion"]["support"] = "direct"
        return caps

    def compile(self, recipe, segment, text, assets):
        result = super().compile(recipe, segment, text, assets)
        result["instruction"] = "，".join(x for x in [result["options"]["instructions"],
            STYLE_TEXT[result["delivery"]], "" if result["emotion"] == "neutral" else result["emotion"]] if x)
        return result

    def _remote(self, request, output_path, context):
        connection = context.get("connection", {})
        base = str(connection.get("base_url", "")).rstrip("/")
        url = urlsplit(base)
        if not connection.get("api_key") or url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment:
            raise ProviderError("connection_missing", "MiMo 连接地址或凭据缺失")
        if connection.get("provider_id", self.provider_id) != self.provider_id:
            raise ProviderError("connection_mismatch", "连接协议与 MiMo 引擎不符")
        p = request["parameters"]
        messages = [{"role": "user", "content": p["instruction"]}] if p["instruction"] else []
        messages.append({"role": "assistant", "content": request["text"]})
        body = {"model": request["model"], "messages": messages, "audio": {"voice": p["variant"]["value"], "format": "wav"}}
        endpoint = base if url.path.endswith("/chat/completions") else base + "/chat/completions"
        return self._http_audio(endpoint, {"Authorization": "Bearer " + connection["api_key"]}, body, output_path, connection, chat_audio=True)
