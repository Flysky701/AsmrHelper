from copy import deepcopy
import json

import pytest

from src.provider_profiles import project_profiles
from src.recovery_connections import capture_recovery_connections, restore_recovery_connections
from src.task_connection_context import capture_connections


def _settings():
    return project_profiles({"api": {}, "connection_profiles": {
        "active_llm": "first", "active_tts": "tts-first",
        "llm": [
            {"id": "first", "name": "First", "provider": "deepseek", "model": "model-a",
             "base_url": "https://one.example", "api_key": "llm-secret"},
            {"id": "second", "name": "Second", "provider": "deepseek", "model": "model-b",
             "base_url": "https://two.example", "api_key": "other-secret"}],
        "tts": [
            {"id": "tts-first", "name": "TTS", "provider": "openai_compatible", "model": "speech-a",
             "base_url": "https://tts.example", "api_key": "tts-secret", "voice": "voice-a",
             "options": {"headers": {"custom": "nested-secret"}}, "instructions": "private instruction"},
            {"id": "tts-second", "name": "Other", "provider": "openai_compatible",
             "base_url": "https://other-tts.example", "api_key": "other-tts-secret"}]}})


def test_original_connections_survive_selection_change_and_rename():
    settings = _settings()
    snapshot = capture_connections(settings)
    record = capture_recovery_connections(settings, snapshot)
    settings["connection_profiles"].update(active_llm="second", active_tts="tts-second")
    settings["connection_profiles"]["llm"][0]["name"] = "Renamed"
    project_profiles(settings)
    assert restore_recovery_connections(json.loads(json.dumps(record)), settings) == snapshot
    for secret in ("llm-secret", "tts-secret", "nested-secret", "private instruction"):
        assert secret not in json.dumps(record)


@pytest.mark.parametrize("kind,field,value", [
    ("llm", "api_key", "rotated"), ("llm", "base_url", "https://changed.example"),
    ("llm", "model", "changed-model"), ("llm", "provider", "openai"),
    ("tts", "voice", "changed-voice"), ("tts", "instructions", "changed-instruction"),
    ("tts", "options", {"headers": {"custom": "rotated-secret"}}),
])
def test_definition_or_credential_change_blocks_resume(kind, field, value):
    settings = _settings()
    record = capture_recovery_connections(settings, capture_connections(settings))
    settings["connection_profiles"][kind][0][field] = value
    with pytest.raises(ValueError, match="无法继续任务") as error:
        restore_recovery_connections(record, settings)
    assert "rotated-secret" not in str(error.value)


def test_deleted_original_never_falls_back_to_active_profile():
    settings = _settings()
    record = capture_recovery_connections(settings, capture_connections(settings))
    settings["connection_profiles"]["llm"].pop(0)
    settings["connection_profiles"]["active_llm"] = "second"
    with pytest.raises(ValueError, match="无法继续任务"):
        restore_recovery_connections(record, settings)


def test_legacy_environment_credentials_are_referenced_and_verified(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-secret")
    settings = {"api": {"provider": "deepseek", "deepseek_api_key": "file-secret",
                        "deepseek_base_url": "https://legacy.example"}, "external_tts": {}}
    snapshot = deepcopy(settings)
    snapshot["api"]["deepseek_api_key"] = "environment-secret"
    record = capture_recovery_connections(settings, snapshot)
    assert restore_recovery_connections(record, settings) == snapshot
    assert "environment-secret" not in json.dumps(record)
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(ValueError, match="无法继续任务"):
        restore_recovery_connections(record, settings)


def test_urls_with_credentials_are_not_persisted_and_still_verified():
    settings = _settings()
    settings["connection_profiles"]["tts"][0]["base_url"] = "https://user:password@example.test/v1?key=query-secret#fragment-secret"
    project_profiles(settings)
    snapshot = capture_connections(settings)
    record = capture_recovery_connections(settings, snapshot)
    assert restore_recovery_connections(record, settings) == snapshot
    for secret in ("password", "query-secret", "fragment-secret", "user:"):
        assert secret not in json.dumps(record)


def test_salts_differ_and_restore_returns_independent_copy():
    settings = _settings()
    snapshot = capture_connections(settings)
    first = capture_recovery_connections(settings, snapshot)
    second = capture_recovery_connections(settings, snapshot)
    assert first["salt"] != second["salt"]
    assert first["template"]["api"]["deepseek_api_key"] != second["template"]["api"]["deepseek_api_key"]
    restored = restore_recovery_connections(first, settings)
    restored["external_tts"]["options"]["headers"]["custom"] = "mutation"
    assert restore_recovery_connections(first, settings) == snapshot


def test_empty_legacy_snapshot_and_unsupported_schema():
    settings = {"api": {}, "external_tts": {}}
    record = capture_recovery_connections(settings, settings)
    assert restore_recovery_connections(record, settings) == settings
    record["schema_version"] = 99
    with pytest.raises(ValueError, match="无法继续任务"):
        restore_recovery_connections(record, settings)


def test_missing_references_cannot_silently_use_current_connection():
    settings = _settings()
    record = capture_recovery_connections(settings, capture_connections(settings))
    record["references"] = []
    with pytest.raises(ValueError, match="无法继续任务"):
        restore_recovery_connections(record, settings)
