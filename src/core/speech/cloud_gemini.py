"""Gemini 3.8 single-speaker Interactions adapter (no Google SDK).

Contract: https://ai.google.dev/gemini-api/docs/speech-generation
Checked 2026-10-13; protocol fixtures are not live API acceptance.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .cloud_http import decode_base64, join_endpoint, post_audio
from .providers import COMMON, ProviderError, SpeechProvider


MODELS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
VOICES = (
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)


def _decode_audio(response):
    """REST returns steps, unlike the SDK's output_audio convenience property."""
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("shape")
        if payload.get("error") or payload.get("status", "completed") != "completed":
            raise ProviderError("remote_incomplete", "Gemini 未返回已完成的合成结果，请确认远端结果后再试", result_unknown=True)
        blocks = [item for step in payload["steps"]
                  if isinstance(step, dict) and step.get("type") == "model_output"
                  for item in step.get("content", [])
                  if isinstance(item, dict) and item.get("type") == "audio"]
        # This matches the official unary REST example / SDK last-audio view.
        audio = blocks[-1]
        content = decode_base64(audio["data"])
        mime = audio.get("mime_type", "audio/wav").lower()
        parts = [part.strip() for part in mime.split(";")]
        if parts[0] in {"audio/wav", "audio/x-wav", "audio/wave"}:
            return content, "audio", None
        if parts[0] == "audio/l16":
            rate = 24000  # Fixed request rate; official 3.8 PCM is LE, mono.
            for part in parts[1:]:
                if part.startswith("rate="):
                    rate = int(part.split("=", 1)[1])
                elif part.startswith("channels=") and part != "channels=1":
                    raise ValueError("channels")
            if rate != 24000:
                raise ValueError("unexpected sample rate")
            return content, "pcm_s16le", rate
        raise ValueError("unsupported audio format")
    except ProviderError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ProviderError("invalid_audio", "Gemini 未返回可解码的单声音音频") from None


class GeminiSpeechProvider(SpeechProvider):
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        self.provider_id, self.name, self.version = "gemini", "Gemini TTS", "1"
        self.remote = self.http = True
        self.options_schema = {**COMMON, "style_description": {
            "type": "string", "maxLength": 500, "default": "",
            "title": "Style instructions",
            "description": "Turn-level style metadata; never appended to the spoken text.",
        }}
        self.modes = [{"id": mode, "variant_kinds": [mode], "models": list(MODELS)}
                      for mode in ("builtin", "hosted")]

    def capabilities(self, model=None, mode=None):
        caps = super().capabilities(model, mode)
        supported = model is None or model in MODELS
        for delivery in caps["delivery"].values():
            delivery["support"] = "direct" if supported else "unsupported"
        caps["emotion"]["support"] = "direct" if supported else "unsupported"
        caps["languages"] = ["zh", "en", "ja"]
        caps["language_control"] = "automatic"
        return caps

    def runtime_options(self, model, mode):
        return ["style_description"] if model in MODELS and mode in {"builtin", "hosted"} else []

    def voice_sources(self, mode):
        if mode == "builtin":
            return {"kind": mode, "presets": [{"id": name, "name": name} for name in VOICES],
                    "default": "Kore", "required": True, "allow_custom": False,
                    "description": "Gemini studio voices; language follows the input text."}
        return {"kind": mode, "presets": [], "default": None, "required": True,
                "allow_custom": True, "description": "Existing persistent voice_ ID from your Gemini account; this does not create a voice."}

    def validate(self, recipe, assets):
        super().validate(recipe, assets)
        voice = recipe["variant"]["value"]
        if recipe["mode"] == "builtin" and voice not in VOICES:
            raise ProviderError("invalid_variant", "请选择 Gemini 的真实内置音色")
        if recipe["mode"] == "hosted" and not re.fullmatch(r"voice_[A-Za-z0-9_-]+", voice):
            raise ProviderError("invalid_variant", "请填写已有的 Gemini voice_ 音色 ID")
        # The app's initial integration supports these output-text languages.
        # Gemini infers speech language from text; this is NOT a force-language field.
        language = recipe.get("language", "auto").lower().replace("_", "-").split("-", 1)[0]
        if language not in {"auto", "zh", "en", "ja"}:
            raise ProviderError("invalid_language", "当前 Gemini 接入支持自动识别、中、英、日文本语言")

    def _remote(self, request, output_path, context):
        connection = context.get("connection", {})
        base, key = str(connection.get("base_url", "")).rstrip("/"), connection.get("api_key")
        parsed = urlsplit(base)
        if not key or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
            raise ProviderError("connection_missing", "外部连接地址或凭据缺失")
        if connection.get("provider_id", self.provider_id) != self.provider_id:
            raise ProviderError("connection_mismatch", "连接协议与引擎不符")
        params = request["parameters"]
        # Revalidate model/voice/options from frozen input before any billable call.
        frozen = {"model": request["model"], "mode": request["mode"],
                  "variant": params["variant"], "language": params["language"],
                  "provider_options": params["options"], "connection_ref": request["connection_ref"]}
        checked = self.compile(frozen, params, request["text"], {})
        if params != checked:
            raise ProviderError("invalid_snapshot", "Gemini 编译快照参数不一致，请重新编译")
        style = [checked["options"]["style_description"].strip()]
        style.append({"normal": "", "soft": "soft tone", "whisper": "whispering"}[checked["delivery"]])
        if checked["emotion"] != "neutral":
            style.append(checked["emotion"])
        text = {"type": "text", "text": request["text"]}
        instructions = "; ".join(part for part in style if part)
        if instructions:
            text["annotations"] = [{"type": "speech_metadata", "style": instructions}]
        body = {"model": request["model"], "input": [{"type": "user_input", "content": [text]}],
                "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
                "generation_config": {"speech_config": [{"voice": checked["variant"]["value"]}]},
                "stream": False, "store": False}
        return post_audio(join_endpoint(base, "/interactions"), {"x-goog-api-key": key},
                          body, output_path, connection, decoder=_decode_audio)
