"""ElevenLabs' single-voice, non-streaming Text to Speech adapter."""
from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import quote

from .providers import COMMON, ProviderError, SpeechProvider, _number


MODELS = ("eleven_v3", "eleven_flash_v2_5", "eleven_v4")
LANGUAGES = ("auto", "zh", "en", "ja")
TEXT_LIMITS = {"eleven_v3": 5000, "eleven_flash_v2_5": 40000, "eleven_v4": 10000}


class ElevenLabsSpeechProvider(SpeechProvider):
    default_base_url = "https://api.elevenlabs.io"
    version = "1"

    def __init__(self):
        self.provider_id, self.name = "elevenlabs", "ElevenLabs"
        self.remote = self.http = True
        self.options_schema = {
            **deepcopy(COMMON),
            "speed": {**_number(.7, 1.2, 1), "title": "Speed",
                "applies_to_models": ["eleven_flash_v2_5"]},
            "stability": {**_number(0, 1, .5), "title": "Stability",
                "model_overrides": {"eleven_v3": {"enum": [0, .5, 1]}}},
            "similarity_boost": {**_number(0, 1, .75), "title": "Voice similarity",
                "applies_to_models": ["eleven_flash_v2_5", "eleven_v4"]},
        }
        self.modes = [{"id": "hosted", "variant_kinds": ["hosted"], "models": list(MODELS)}]

    def capabilities(self, model=None, mode=None):
        result = super().capabilities(model, mode)
        result["languages"] = list(LANGUAGES)
        result["max_text_length"] = TEXT_LIMITS.get(model, min(TEXT_LIMITS.values()))
        return result

    def runtime_options(self, model, mode):
        if model not in MODELS or mode != "hosted":
            return []
        return [key for key, rule in self.options_schema.items()
                if key != "schema_version" and model in rule.get("applies_to_models", MODELS)]

    def voice_sources(self, mode):
        return {"kind": "hosted", "presets": [], "default": None, "required": True,
            "allow_custom": True, "description": "Choose an account voice or enter its ID"}

    def _options(self, recipe):
        supplied = recipe.get("provider_options")
        if (recipe.get("model") == "eleven_v3" and isinstance(supplied, dict)
                and type(supplied.get("speed")) in (float, int) and supplied["speed"] == 1):
            # Previous versions stored the neutral speed on every v3 recipe.
            supplied = {k: v for k, v in supplied.items() if k != "speed"}
            recipe = {**recipe, "provider_options": supplied}
        validated = super()._options(recipe)
        # Unspecified controls inherit this voice's settings on the account.
        return {k: v for k, v in validated.items() if k in supplied}

    def validate(self, recipe, assets):
        super().validate(recipe, assets)
        variant = recipe["variant"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", variant["value"]):
            raise ProviderError("invalid_variant", "Choose an account voice or enter its ID, not a URL")
        if variant.get("style", "normal") != "normal":
            raise ProviderError("unsupported_intent", "This adapter does not promise a hosted voice's delivery style")
        if recipe.get("language", "auto") not in LANGUAGES:
            raise ProviderError("invalid_language", "This adapter supports auto, zh, en and ja")

    def compile(self, recipe, segment, text, assets):
        params = super().compile(recipe, segment, text, assets)
        if not isinstance(text, str) or not text.strip() or len(text) > TEXT_LIMITS[recipe["model"]]:
            raise ProviderError("invalid_text", "Text is empty or exceeds the selected ElevenLabs model limit")
        return params

    def _remote(self, request, output_path, context):
        from .cloud_http import join_endpoint, post_audio

        connection = context.get("connection", {})
        if connection.get("provider_id") != self.provider_id:
            raise ProviderError("connection_mismatch", "Select an ElevenLabs connection")
        if not connection.get("api_key") or not connection.get("base_url"):
            raise ProviderError("connection_missing", "The ElevenLabs connection needs an address and credential")
        params = request.get("parameters", {})
        if not isinstance(params, dict) or set(params) - {"language", "variant", "options", "delivery", "emotion"}:
            raise ProviderError("invalid_options", "Unsupported ElevenLabs request parameters")
        # Revalidate the frozen request at the execution boundary; never drop an
        # unsupported parameter introduced by a stale or modified snapshot.
        recipe = {"provider_id": self.provider_id, "model": request.get("model"),
            "mode": request.get("mode"), "connection_ref": request.get("connection_ref"),
            "variant": params.get("variant"), "language": params.get("language", "auto"),
            "provider_options": params.get("options")}
        recompiled = self.compile(recipe, params, request.get("text"), {})
        expected = params
        legacy_options = params.get("options", {})
        if (request["model"] == "eleven_v3" and type(legacy_options.get("speed")) in (float, int)
                and legacy_options["speed"] == 1):
            expected = {**params, "options": {k: v for k, v in legacy_options.items() if k != "speed"}}
        if recompiled != expected:
            raise ProviderError("snapshot_mismatch", "The ElevenLabs request differs from its compiled parameters")
        params = recompiled
        options = params["options"]
        body = {"text": request["text"], "model_id": request["model"]}
        voice_settings = {key: options[key] for key in self.runtime_options(request["model"], "hosted")
                          if key in options}
        if voice_settings:
            body["voice_settings"] = voice_settings
        if params["language"] != "auto":
            body["language_code"] = params["language"]
        voice_id = quote(params["variant"]["value"], safe="")
        url = join_endpoint(connection["base_url"], f"/v1/text-to-speech/{voice_id}")
        return post_audio(url + "?output_format=wav_24000",
            {"xi-api-key": connection["api_key"], "Content-Type": "application/json", "Accept": "audio/wav"},
            body, output_path, connection)
