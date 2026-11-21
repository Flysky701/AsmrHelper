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


def test_local_preflight_and_save_without_llm_credentials(service, tmp_path):
    output = str(tmp_path / 'output')
    updates = {'paths': {'output_dir': output}}
    before = deepcopy(service.config.get_file_config())
    valid, errors, _ = service.validate_settings(updates)
    assert valid, errors
    assert service.config.get_file_config() == before
    assert service.update_settings(updates)['paths']['output_dir'] == output
    service.config.reload()
    assert service.config.get('paths.output_dir') == output
    assert not service.config.deepseek_api_key


def test_invalid_local_value_still_rejected_by_both_paths(service):
    updates = {'processing': {'original_volume': 99}}
    before = deepcopy(service.config.get_file_config())
    valid, errors, _ = service.validate_settings(updates)
    assert not valid and any('original_volume' in e for e in errors)
    with pytest.raises(AppValidationError, match='original_volume'):
        service.update_settings(updates)
    assert service.config.get_file_config() == before
