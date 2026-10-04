"""Directory contracts across settings, status, tasks and installation planning."""
import importlib
import threading
from pathlib import Path

import pytest

from src.config import config
from src.workspace_paths import model_directory, temporary_directory, directory_context, path_setting_errors


@pytest.fixture
def roots(tmp_path, monkeypatch):
    values = {'model_cache_dir': str(tmp_path / '模型 with spaces'),
              'output_dir': str(tmp_path / '输出'), 'temp_dir': str(tmp_path / '临时 A')}
    original = config.get
    monkeypatch.setattr(config, 'get', lambda key, default=None: values.get(key[6:], default)
                        if key.startswith('paths.') else original(key, default))
    monkeypatch.delenv('ASMR_HELPER_MODEL_ROOT', raising=False)
    monkeypatch.delenv('ASMR_HELPER_TEMP_ROOT', raising=False)
    return values


def test_status_and_install_reference_share_saved_model_root(roots, tmp_path):
    from src.core.runtime.service import RuntimeWorkspaceManager
    from src.core.resources.model_catalog import ModelCatalog
    from src.core.resources.model_reference import resolve_model_reference
    from src.core.resources.model_installer import ModelInstaller
    manager = RuntimeWorkspaceManager(tmp_path)
    statuses = {s.name:s for s in manager.check_required_resources()}
    root = Path(roots['model_cache_dir'])
    assert statuses['models_dir'].metadata['path'] == str(root)
    assert not statuses['models_dir'].available and not root.exists()
    entry = ModelCatalog().get('faster-whisper-tiny')
    expected = root / 'whisper/tiny'
    assert entry.resolved_install_dir() == expected
    command, _ = ModelInstaller(tmp_path)._build_download_cmd(entry, 'whisper', None)
    assert repr(str(expected)) in command[-1]
    expected.mkdir(parents=True)
    assert resolve_model_reference(entry.id) == str(expected)
    assert {s.name:s for s in manager.check_required_resources()}['models_dir'].available


def test_directory_context_freezes_installer_verification_and_worker_env(roots, tmp_path):
    from src.core.runtime.profiles import RuntimeProfileResolver
    from src.core.resources.model_catalog import ModelCatalog
    original_root = model_directory()
    original_temp = temporary_directory()
    with directory_context():
        roots.update(model_cache_dir=str(tmp_path/'later-models'), temp_dir=str(tmp_path/'later-temp'))
        assert ModelCatalog().get('qwen3-asr-0.6b').resolved_install_root() == original_root
        env = RuntimeProfileResolver(project_root=tmp_path).subprocess_env()
        assert Path(env['ASMR_HELPER_MODEL_ROOT']) == original_root
        assert Path(env['ASMR_HELPER_TEMP_ROOT']) == original_temp
    assert model_directory() == tmp_path/'later-models'


def test_environment_model_override_is_consistent(roots, monkeypatch, tmp_path):
    from src.core.runtime.service import RuntimeWorkspaceManager
    from src.core.resources.model_catalog import ModelCatalog
    override = tmp_path/'deployment-models'
    monkeypatch.setenv('ASMR_HELPER_MODEL_ROOT', str(override))
    assert Path(RuntimeWorkspaceManager(tmp_path).resolve_workspace().models_dir) == override
    assert ModelCatalog().get('qwen3-base').resolved_install_root() == override


def test_new_session_refresh_keeps_existing_session_snapshot(roots, tmp_path):
    from src.app.services.session_service import SessionService
    from src.app.services.input_catalog_service import InputCatalogService
    from src.core.sessions.models import WorkspaceContext
    from types import SimpleNamespace
    catalog = InputCatalogService()
    source = tmp_path/'sample.vtt'; source.write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nTest\n')
    asset = catalog.inspect_paths([str(source)])[0]
    workspace = SimpleNamespace(resolve=lambda: WorkspaceContext('w',str(tmp_path), roots['output_dir'],roots['temp_dir'],roots['model_cache_dir']))
    service = SessionService(workspace_service=workspace, input_catalog_service=catalog)
    args = dict(workspace_id='w', mode='test', input_asset_ids=[asset.asset_id], primary_input_asset_id=asset.asset_id)
    first = service.create_session(**args)
    roots.update(temp_dir=str(tmp_path/'临时 B'), output_dir=str(tmp_path/'输出 B'))
    second = service.create_session(**args)
    assert Path(first.resolved_temp_dir).parent != Path(second.resolved_temp_dir).parent
    assert Path(second.resolved_temp_dir).parent == tmp_path/'临时 B'
    assert service.get_session(first.session_id) == first


def test_queued_and_running_task_roots_are_frozen(roots, tmp_path):
    from src.app.services.task_service import TaskService
    from src.core.tasks.dispatcher import TaskDispatcher
    tasks = TaskService()
    dispatcher = TaskDispatcher(tasks._registry, task_service=tasks)
    before = model_directory()
    started, release = threading.Event(), threading.Event()
    found=[]
    def execute(spec, context):
        found.append(model_directory());started.set();assert release.wait(5);found.append(model_directory())
    dispatcher.register_executor('directory-probe', execute)
    spec,_ = tasks.create_task_spec(task_type='directory-probe',task_source='test',session_id='')
    roots['model_cache_dir'] = str(tmp_path/'changed-before-start')
    dispatcher.submit(spec.task_id);assert started.wait(5)
    roots['model_cache_dir'] = str(tmp_path/'changed-while-running')
    release.set();dispatcher.run(spec.task_id)
    assert found == [before,before]


def test_path_validation_rejects_files_and_types_without_creating_target(tmp_path):
    existing = tmp_path/'file';existing.write_text('preserve')
    assert path_setting_errors({'temp_dir': str(existing/'child')})
    assert path_setting_errors({'model_cache_dir': 42})
    target=tmp_path/'新目录 with spaces'/'child'
    assert path_setting_errors({'output_dir':str(target)}) == []
    assert not target.exists() and existing.read_text() == 'preserve'


def test_status_does_not_treat_a_file_as_a_directory(roots, tmp_path):
    from src.core.runtime.service import RuntimeWorkspaceManager
    file=Path(roots['model_cache_dir']);file.write_text('preserve')
    status={s.name:s for s in RuntimeWorkspaceManager(tmp_path).check_required_resources()}['models_dir']
    assert not status.available and status.detail == 'not a directory'
