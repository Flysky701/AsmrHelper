"""Focused beta.4 bootstrap contract tests; no model/network/build operations.

Run after integration with project Python:
  python -m pytest <this-file> -q -p no:cacheprovider
"""
import importlib.util
import os
from pathlib import Path
import sys

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('beta4_bootstrap_under_test', REPOSITORY / 'scripts' / 'desktop_backend.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

# Every existing externally supplied cache is intentionally outside the workspace.
# beta.4 promises app-scoped cache placement, so setdefault is not sufficient.
CACHE_VARIABLES = (
    'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'PIP_CACHE_DIR',
    'HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'TRANSFORMERS_CACHE',
    'TORCH_HOME', 'NUMBA_CACHE_DIR', 'XDG_CACHE_HOME', 'TEMP', 'TMP',
)

@pytest.fixture
def environment(monkeypatch, tmp_path):
    original_cwd = Path.cwd()
    original_sys_path = sys.path[:]
    with monkeypatch.context() as patch:
        # Restores all writes performed directly by configure_environment.
        patch.setattr(os, 'environ', dict(os.environ))
        for key in CACHE_VARIABLES:
            os.environ[key] = str(tmp_path / 'old-outside-workspace' / key)
        bundle = tmp_path / 'bundle'
        data = tmp_path / 'workspace Chinese spaces'
        data.mkdir()
        yield bundle, data
    os.chdir(original_cwd)
    sys.path[:] = original_sys_path


def assert_inside(path, root):
    # Windows canonical paths may include the extended-length prefix.
    clean = str(path).removeprefix('\\\\?\\')
    assert Path(clean).resolve().is_relative_to(root.resolve()), (clean, str(root))


def test_cache_environment_overrides_inherited_locations(environment):
    bundle, data = environment
    bootstrap.configure_environment(bundle, data)
    for key in CACHE_VARIABLES:
        assert key in os.environ, key
        assert_inside(os.environ[key], data)
    assert_inside(os.environ['ASMR_HELPER_STATE_DB'], data)
    assert Path(os.environ['TEMP']).is_dir()
    assert Path(os.environ['TMP']).is_dir()


def test_workspace_change_does_not_retain_previous_cache_roots(environment):
    bundle, first = environment
    second = first.parent / 'second workspace'
    second.mkdir()
    bootstrap.configure_environment(bundle, first)
    bootstrap.configure_environment(bundle, second)
    for key in CACHE_VARIABLES:
        assert_inside(os.environ[key], second)


def test_cache_configuration_precedes_runtime_preparation(environment, monkeypatch):
    bundle, data = environment
    monkeypatch.setattr(sys, 'argv', ['desktop_backend.py', '--data-dir', str(data), '--port', '9999'])
    os.environ['ASMR_HELPER_DESKTOP_TOKEN'] = 'test-only-never-a-real-credential-' * 2
    os.environ.pop('ASMR_HELPER_START_GATE', None)
    calls = []

    def prepare(_bundle, selected_data):
        calls.append('prepare')
        for key in CACHE_VARIABLES:
            assert_inside(os.environ[key], data)
        return selected_data / 'runtimes' / 'fake-python.exe'

    monkeypatch.setattr(bootstrap, 'prepare_runtime', prepare)
    monkeypatch.setattr(bootstrap.subprocess, 'call', lambda command: calls.append('spawn') or 0)
    assert bootstrap.main() == 0
    assert calls == ['prepare', 'spawn']
