from copy import deepcopy
import json

import pytest

from src.app.services.legacy_speech_import import inspect_legacy, import_legacy
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech.store import SpeechStore
from src.app.services.settings_service import SettingsService
from src.app.errors import AppValidationError
from src.task_connection_context import capture_connections


@pytest.fixture
def service(tmp_path):
    return SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=TaskService(), artifacts=ArtifactService())


def test_import_is_additive_idempotent_and_never_exposes_credentials(service):
    old = {"external_tts": {"api_format": "fish", "base_url": "https://api.fish.audio/v1",
           "api_key": "test-secret-do-not-expose", "model": "s2-pro", "voice": "my-voice"},
           "tts": {"engine": "unknown-historical"}}
    original = deepcopy(old)
    existing = service.save_connection({"name": "current", "provider_id": "edge", "deployment": "cloud"})
    existing_record = service.store.get("connections", existing["id"])
    assert inspect_legacy(old, service)["entries"][0]["status"] == "ready"
    report = import_legacy(old, service)
    assert report["entries"][0]["status"] == "imported"
    assert set(report["entries"][0]["retained_fields"]) == {"model", "voice"}
    assert "test-secret" not in json.dumps(report)
    assert "test-secret" not in json.dumps(service.store.list("imports"))
    imported = service.store.get("connections", report["entries"][0]["connection_id"])
    assert service.connection_context(imported)["connection"]["api_key"] == "test-secret-do-not-expose"
    assert imported["provider_id"] == "fish_audio"
    assert service.store.get("connections", existing["id"]) == existing_record
    import_legacy(old, service)
    assert len(service.store.list("connections")) == 2
    assert old == original
    assert service.store.list("recipes") == []


def test_unmappable_entries_do_not_block_valid_entries(service):
    old = {"connection_profiles": {"tts": [
        {"id": "bad", "api_format": "unknown", "base_url": "https://example.com"},
        {"id": "good", "api_format": "speech", "base_url": "https://example.com/v1"}]}}
    report = import_legacy(old, service)
    assert [x["status"] for x in report["entries"]] == ["retained", "imported"]
    assert len(service.store.list("connections")) == 1


def test_new_settings_and_task_context_ignore_legacy_tts():
    service = SettingsService()
    for update in ({"external_tts": {}}, {"tts": {}}):
        with pytest.raises(AppValidationError, match="Speech"):
            service._to_internal_updates(update)
    assert capture_connections({"api": {"provider": "deepseek"}, "external_tts": {"api_key": "old"}}) == {
        "api": {"provider": "deepseek"}}


@pytest.mark.parametrize("bad", [{"api_format": []}, {"api_format": {"bad": True}},
                                  {"api_key": ["bad"]}, None])
def test_malformed_entry_retained_without_blocking_import(service, bad):
    value = {"base_url": "https://bad.example", **bad} if isinstance(bad, dict) else bad
    # A falsey list is still an invalid explicit protocol, not the default.
    settings = {"connection_profiles": {"tts": [value,
        {"id": "valid", "api_format": "speech", "base_url": "https://valid.example"}]}}
    original = deepcopy(settings)
    report = import_legacy(settings, service)
    assert [x["status"] for x in report["entries"]] == ["retained", "imported"]
    assert len(service.store.list("connections")) == 1
    assert settings == original


def test_new_llm_profiles_do_not_inspect_invalid_legacy_tts():
    from src.provider_profiles import profiles_for
    profiles = profiles_for({"external_tts": None})
    assert profiles["active_llm"] == "legacy-deepseek"
    assert "tts" not in profiles
