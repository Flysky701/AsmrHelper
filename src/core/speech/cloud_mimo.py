"""MiMo's chat-completions TTS contract (built-in voices, non-streaming)."""
from __future__ import annotations

from urllib.parse import urlsplit

from .cloud_http import decode_base64, join_endpoint, post_audio
from .providers import COMMON, ProviderError, SpeechProvider


VOICES = (
    ("mimo_default", "MiMo default (region dependent)", "auto"),
    ("冰糖", "冰糖", "zh"), ("茉莉", "茉莉", "zh"),
    ("苏打", "苏打", "zh"), ("白桦", "白桦", "zh"),
    ("Mia", "Mia", "en"), ("Chloe", "Chloe", "en"),
    ("Milo", "Milo", "en"), ("Dean", "Dean", "en"),
)


class MimoSpeechProvider(SpeechProvider):
    default_base_url = "https://api.xiaomimimo.com/v1"

    def __init__(self):
        self.provider_id, self.name, self.version = "mimo", "MiMo TTS", "1"
        self.remote = self.http = True
        self.options_schema = {**COMMON, "style_description": {
            "type": "string", "maxLength": 2000, "default": "",
            "title": "Speech style", "description": "Natural-language delivery instructions; not spoken text."}}
        self.modes = [{"id": "builtin", "variant_kinds": ["builtin"], "models": ["mimo-v2.5-tts"]}]

    def capabilities(self, model=None, mode=None):
        caps = super().capabilities(model, mode)
        for delivery in caps["delivery"].values():
            delivery.update(support="direct", evidence="unverified")
        caps["emotion"] = {"support": "direct", "evidence": "unverified"}
        # Only documented Chinese/English built-in voices are exposed initially.
        caps["languages"] = ["zh", "en"]
        return caps

    def runtime_options(self, model, mode):
        return ["style_description"] if model == "mimo-v2.5-tts" and mode == "builtin" else []

    def voice_sources(self, mode):
        return {"kind": mode, "presets": [{"id": key, "name": name, "language": lang}
                for key, name, lang in VOICES] if mode == "builtin" else [],
            "default": "mimo_default" if mode == "builtin" else None,
            "required": True, "allow_custom": False,
            "description": "Built-in MiMo voices; mimo_default depends on the service region."}

    def validate(self, recipe, assets):
        super().validate(recipe, assets)
        if recipe["variant"]["value"] not in {voice[0] for voice in VOICES}:
            raise ProviderError("invalid_variant", "MiMo TTS requires a documented built-in voice")
        if recipe.get("language", "auto") not in {"auto", "zh", "en"}:
            raise ProviderError("invalid_language", "MiMo integration currently supports auto, Chinese and English")

    def compile(self, recipe, segment, text, assets):
        params = super().compile(recipe, segment, text, assets)
        cues = []
        if params["language"] != "auto":
            cues.append("Speak in " + {"zh": "Chinese", "en": "English"}[params["language"]] + ".")
        if params["delivery"] != "normal":
            cues.append({"soft": "Use a soft, gentle tone.", "whisper": "Whisper the speech."}[params["delivery"]])
        if params["emotion"] != "neutral":
            cues.append("Express a " + params["emotion"] + " emotion.")
        description = params["options"]["style_description"].strip()
        if description:
            cues.append(description)
        params["instruction"] = " ".join(cues)
        return params

    def _remote(self, request, output_path, context):
        connection = context.get("connection", {})
        base, key = str(connection.get("base_url", "")).rstrip("/"), connection.get("api_key")
        parsed = urlsplit(base)
        if not key or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
            raise ProviderError("connection_missing", "MiMo connection URL or API key is missing")
        if connection.get("provider_id", self.provider_id) != self.provider_id:
            raise ProviderError("connection_mismatch", "Connection provider does not match MiMo")
        params = request["parameters"]
        # Revalidate the frozen request before any billable operation.
        recipe = {"model": request["model"], "mode": request["mode"], "connection_ref": request["connection_ref"],
            "variant": params["variant"], "language": params["language"], "provider_options": params["options"]}
        expected = self.compile(recipe, params, request["text"], {})
        if params != expected:
            raise ProviderError("invalid_snapshot", "MiMo compiled parameters do not match the provider contract")
        messages = []
        if params["instruction"]:
            messages.append({"role": "user", "content": params["instruction"]})
        messages.append({"role": "assistant", "content": request["text"]})
        body = {"model": request["model"], "messages": messages,
            "audio": {"format": "wav", "voice": params["variant"]["value"]}, "stream": False}
        return post_audio(join_endpoint(base, "/chat/completions"), {"api-key": key}, body,
            output_path, connection, decoder=self._decode_response)

    @staticmethod
    def _decode_response(response):
        try:
            payload = response.json()
            choices = payload["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("one audio completion required")
            choice = choices[0]
            reason = choice.get("finish_reason")
            if reason == "content_filter":
                raise ProviderError("content_filtered", "MiMo declined to generate this speech")
            if reason != "stop":
                raise ProviderError("incomplete_audio", "MiMo did not finish the audio generation")
            encoded = choice["message"]["audio"]["data"]
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("invalid_audio", "MiMo response does not contain a complete audio result") from None
        return decode_base64(encoded), "audio", None
