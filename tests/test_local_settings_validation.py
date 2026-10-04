"""Real Config regressions for the settings UI preflight-then-save sequence."""
import importlib
from copy import deepcopy

import pytest

from src.app.errors import AppValidationError
from src.app.services.settings_service import SettingsService


@pytest.fixture
def service(tmp_path, monkeypatch):
    module = importlib.import_module('src.config')
    monkeypatch.setattr(module, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(module, 'CONFIG_DIR', tmp_path)
    for name in ('DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    cfg = object.__new__(module.Config)
    cfg.save({})
    cfg.reload()
    return SettingsService(config_manager=cfg)


@pytest.mark.parametrize('migrated', [False, True])
@pytest.mark.parametrize('section,field,value', [
    ('paths', 'output_dir', 'D:/output'),
    ('paths', 'vtt_dir', 'D:/subtitles'),
    ('paths', 'model_cache_dir', 'D:/models'),
    ('paths', 'temp_dir', 'D:/temporary'),
    ('processing', 'asr_model', 'faster-whisper-small'),
    ('processing', 'original_volume', 0.7),
])
def test_local_preflight_and_save_without_llm_credentials(service, migrated, section, field, value, tmp_path):
    if migrated:
        # An unrelated incomplete saved LLM profile must not block local settings.
        service.config.persist_updates({'connection_profiles': {
            'active_llm': 'incomplete', 'llm': [{'id': 'incomplete', 'name': 'Unconfigured',
            'provider': 'deepseek', 'base_url': 'https://api.deepseek.com', 'model': '', 'api_key': ''}]}})
    if section == 'paths':
        value = str(tmp_path / field)
    updates = {section: {field: value}}
    before = deepcopy(service.config.get_file_config())
    valid, errors, _ = service.validate_settings(updates)
    assert valid, errors
    assert service.config.get_file_config() == before
    assert service.update_settings(updates)[section][field] == value
    service.config.reload()
    assert service.config.get(f'{section}.{field}') == value
    assert not service.config.deepseek_api_key


def test_invalid_local_value_still_rejected_by_both_paths(service):
    updates = {'processing': {'original_volume': 99}}
    before = deepcopy(service.config.get_file_config())
    valid, errors, _ = service.validate_settings(updates)
    assert not valid and any('original_volume' in e for e in errors)
    with pytest.raises(AppValidationError, match='original_volume'):
        service.update_settings(updates)
    assert service.config.get_file_config() == before


def test_deepseek_configuration_and_probe_still_require_own_key(service):
    updates = {'providers': {'default_llm': 'deepseek'}}
    valid, errors, _ = service.validate_settings(updates)
    assert not valid and any('API Key' in e for e in errors)
    with pytest.raises(AppValidationError, match='API Key'):
        service.update_settings(updates)
    result = service.test_provider('deepseek')
    assert not result.success and result.error_code == 'PROVIDER_CREDENTIAL_MISSING'
