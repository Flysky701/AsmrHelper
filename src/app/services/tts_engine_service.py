"""Command-line compatibility facade over the single Speech execution service."""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

from ..dto import SynthesisResult
from ..errors import AppExecutionError, AppValidationError
from .capability_descriptor_service import get_capability_descriptor_service


class TtsEngineService:
    """Keep standalone TTS callers on the same snapshots/compiler/runner as desktop."""

    def __init__(self, capability_service=None, speech_service=None):
        self._capability_service = capability_service or get_capability_descriptor_service()
        self._speech_service = speech_service

    @property
    def speech(self):
        if self._speech_service is None:
            from .speech_service import get_speech_service
            self._speech_service = get_speech_service()
        return self._speech_service

    def list_engines(self):
        return self._capability_service.list_descriptors(category="tts")

    def get_engine(self, engine_id):
        return self._capability_service.get_descriptor("tts", engine_id)

    def list_supported_models(self, engine_id):
        return self.get_engine(engine_id)["supported_models"]

    def list_voices(self, engine_id):
        from src.core.speech.providers import get_provider
        return [voice for mode in get_provider(engine_id).describe()["modes"]
                for voice in mode["voice_sources"]["presets"]]

    def engine_supports(self, engine_id, feature):
        return bool(self.get_engine(engine_id)["supports"].get(feature, False))

    def synthesize_file(self, input_path, output_path, provider=None, voice=None,
                        model=None, connection_ref=None, recipe_id=None):
        source = Path(input_path)
        if not source.is_file():
            raise AppValidationError(f"input file does not exist: {input_path}")
        return self.synthesize_text(text=source.read_text(encoding="utf-8"), output_path=output_path,
            provider=provider, model=model, common_options={"voice": voice} if voice else {},
            connection_ref=connection_ref, recipe_id=recipe_id)

    def synthesize_text(self, *, text: str, output_path: str, provider=None, model=None,
                        common_options: dict[str, Any] | None = None,
                        provider_options: dict[str, Any] | None = None,
                        connection_ref=None, recipe_id=None):
        try:
            stage = self.build_stage(provider=provider, model=model, common_options=common_options,
                provider_options=provider_options, connection_ref=connection_ref, recipe_id=recipe_id)
            snapshot = self.speech.pipeline_snapshot(stage)
            result_path = self.speech.synthesize_text(snapshot, text, output_path)
        except AppValidationError:
            raise
        except (ValueError, KeyError, FileNotFoundError) as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc
        return SynthesisResult(engine=snapshot["recipe"]["provider_id"],
            voice=snapshot["recipe"]["variant"]["value"], output_path=result_path)


    def build_stage(self, *, provider=None, model=None, common_options=None,
                    provider_options=None, connection_ref=None, recipe_id=None):
        """Single explicit adapter for retained flat CLI/DTO options."""
        from src.core.speech.providers import get_provider
        common, parameters = dict(common_options or {}), dict(provider_options or {})
        if set(common) - {"voice", "language", "speed"}:
            raise AppValidationError("Unsupported legacy TTS options; select a saved Speech rule instead")
        if recipe_id and (connection_ref or common or parameters):
            raise AppValidationError("A saved rule cannot be combined with connection or voice overrides")
        if recipe_id:
            stage = {"provider": provider, "model": model, "options": {"speech_recipe_id": recipe_id}}
        else:
            if connection_ref:
                connection = self.speech.store.get("connections", connection_ref)
                if provider and connection["provider_id"] != provider:
                    raise ValueError("Selected connection and engine differ")
                provider = connection["provider_id"]
            provider = provider or "edge"
            engine = get_provider(provider)
            if "speed" in common and "speed" not in engine.options_schema:
                raise ValueError("This provider does not support speed; use its Speech rule options")
            if common.get("voice") and not any(m["id"] in {"builtin", "hosted"} for m in engine.modes):
                if common["voice"] != engine.voice_sources("default").get("default"):
                    raise ValueError("This engine requires a saved Speech rule for a custom voice")
            source = {"provider_options": {"schema_version": 1, **parameters}}
            if connection_ref:
                source["connection_ref"] = connection_ref
            # Hosted IDs have no built-in catalog and must always be explicit.
            if engine.http and common.get("voice"):
                modes = [m for m in engine.modes if not model or model in m["models"] or not m["models"]]
                if len(modes) != 1:
                    raise ValueError("Select a model or saved rule to identify the voice mode")
                source.update(mode=modes[0]["id"], variant={"kind": modes[0]["id"], "value": common["voice"]})
            stage = {"provider": provider, "model": model, "options": {**common, "speech_source": source}}
        return stage


_service = None
_lock = threading.Lock()


def get_tts_engine_service():
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TtsEngineService()
    return _service
