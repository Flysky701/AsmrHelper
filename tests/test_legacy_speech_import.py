"""Historical TTS settings remain read-only and isolated from active connections."""
import pytest

from src.app.services.settings_service import SettingsService
from src.app.errors import AppValidationError
from src.task_connection_context import capture_connections


def test_new_settings_and_task_context_ignore_legacy_tts():
    service = SettingsService()
    for update in ({"external_tts": {}}, {"tts": {}}):
        with pytest.raises(AppValidationError, match="Speech"):
            service._to_internal_updates(update)
    assert capture_connections({"api": {"provider": "deepseek"}, "external_tts": {"api_key": "old"}}) == {
        "api": {"provider": "deepseek"}}


def test_new_llm_profiles_do_not_inspect_invalid_legacy_tts():
    from src.provider_profiles import profiles_for
    profiles = profiles_for({"external_tts": None})
    assert profiles["active_llm"] == "legacy-deepseek"
    assert "tts" not in profiles
