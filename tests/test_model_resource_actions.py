"""Separate weight/reference operations from runtime preparation without real downloads."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.http.dependencies import model_service
from src.api.http.routes.models import router
from src.api.http.schemas.tasks import TaskStatusResponse
from src.app.services.model_service import ModelService as AppModelService
from src.core.resources import model_assets as assets
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_installer import ModelInstaller
from src.core.resources.model_service import ModelService
from src.core.resources.model_status import ModelStatusResolver, ModelStatusIssue


@pytest.fixture
def entry(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    monkeypatch.setattr(assets, 'PROJECT_ROOT', workspace)
    monkeypatch.setattr(ModelEntry, 'managed_install_dir', lambda self: workspace / 'models' / self.install_path)
    return ModelEntry(id='sample', kind='local', category='asr', provider='sample', display_name='Sample',
                      description='', install_path='family/model', required_files=['config.json', 'model.bin'],
                      supports_install=True, supports_remove=True)


def put_weights(path):
    path.mkdir(parents=True)
    (path / 'config.json').write_text('{}')
    (path / 'model.bin').write_bytes(b'weights')


def test_reference_persists_without_runtime_and_unlink_preserves_files(entry, tmp_path, monkeypatch):
    shared = tmp_path / 'old-models'
    put_weights(shared / entry.install_path)
    assets.add_source(str(shared))
    resolver = ModelStatusResolver(import_checker=lambda _: False)
    monkeypatch.setattr(resolver, '_runtime_issues', lambda _: [ModelStatusIssue('PYTHON_DEPENDENCY_MISSING', 'sample', 'missing')])
    status = resolver.resolve(entry)
    assert status.weights_ready and not status.runtime_ready and not status.executable and status.shared_readonly
    assert status.path == shared / entry.install_path
    installer = ModelInstaller()
    assert installer.install_local_model(entry)
    for action in [lambda: installer.install_local_model(entry, force=True),
                   lambda: installer.install_with_progress(entry, force=True),
                   lambda: installer.remove_local_model(entry)]:
        with pytest.raises(ValueError, match='只读'):
            action()
    assets.remove_source(str(shared))
    assert assets.sources() == []
    assert (shared / entry.install_path / 'model.bin').read_bytes() == b'weights'


def test_dependency_import_is_not_demucs_weight_evidence(entry, monkeypatch):
    monkeypatch.setattr(assets, 'scan_roots', lambda: [])
    status = ModelStatusResolver(import_checker=lambda _: True).resolve(
        replace(entry, provider='demucs', upstream_name='htdemucs', install_strategy='package'))
    assert status.runtime_ready and not status.weights_ready and not status.executable
    assert status.status != 'installed'


def test_demucs_status_does_not_require_unused_torchaudio(entry, monkeypatch):
    monkeypatch.setattr(assets, 'scan_roots', lambda: [])
    status = ModelStatusResolver(import_checker=lambda module: module != 'torchaudio').resolve(
        replace(entry, provider='demucs', upstream_name='htdemucs', install_strategy='package'))
    assert status.runtime_ready
    assert not any(issue.requirement == 'torchaudio' for issue in status.issues)


def test_download_existing_weights_never_probes_runtime(entry, monkeypatch):
    put_weights(entry.managed_install_dir())
    installer = ModelInstaller()
    monkeypatch.setattr(installer._status, 'resolve', lambda _: pytest.fail('runtime probe during weight operation'))
    assert installer.install_local_model(entry)
    assert installer.install_with_progress(entry)


def test_download_does_not_install_dependencies_or_validate_inference(entry, monkeypatch):
    service = ModelService()
    monkeypatch.setattr(service, 'get_model', lambda _: replace(entry, provider='faster_whisper'))
    monkeypatch.setattr(service, '_install_runtime_packages', lambda _: pytest.fail('dependency install'))
    monkeypatch.setattr(service.runtime_resolver, 'verify_ctranslate2', lambda *a, **kw: pytest.fail('inference'))
    monkeypatch.setattr(service.installer, 'install_local_model', lambda *a, **kw: True)
    assert service.install(entry.id, install_dependencies=False)


def test_prepare_runtime_does_not_download(entry, monkeypatch):
    service = ModelService()
    calls = []
    monkeypatch.setattr(service, 'get_model', lambda _: entry)
    monkeypatch.setattr(service, '_install_runtime_packages', lambda _: calls.append('runtime'))
    monkeypatch.setattr(service.status_resolver, '_runtime_issues', lambda _: [])
    monkeypatch.setattr(service.installer, 'install_local_model', lambda *a, **kw: pytest.fail('weight download'))
    assert service.prepare_runtime(entry.id)
    assert calls == ['runtime']


def test_separate_http_routes_and_reference_import(entry, tmp_path, monkeypatch):
    calls = []
    class Service:
        def install_model_async(self, model_id, **kwargs):
            calls.append((model_id, kwargs))
            return TaskStatusResponse(task_id='test', state='pending')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[model_service] = Service
    shared = tmp_path / 'saved-models'
    put_weights(shared / entry.install_path)
    with TestClient(app) as client:
        assert client.post('/models/sources', json={'path': str(shared)}).status_code == 200
        assert calls == []
        assert str(shared) in client.get('/models/sources').json()['roots']
        assert client.post('/models/sample/runtime').status_code == 201
        assert calls[-1][1] == {'operation': 'runtime'}
        assert client.post('/models/sample/download', json={}).status_code == 201
        assert calls[-1][1]['operation'] == 'download' and calls[-1][1]['install_dependencies'] is False
        assert client.post('/models/sample/download', json={'install_dependencies': True}).status_code == 422
        assert client.post('/models/sources/remove', json={'path': str(shared)}).status_code == 200
    assert (shared / entry.install_path / 'model.bin').is_file()


def test_runtime_dispatch_never_enters_weight_installer():
    service = AppModelService.__new__(AppModelService)
    calls = []
    service.core_service = SimpleNamespace(prepare_runtime=lambda mid: calls.append(mid),
                                          install=lambda *a, **k: pytest.fail('download'))
    service._get_model_entry = lambda _: None
    context = SimpleNamespace(cancellation_requested=False, update_progress=lambda *a, **k: None)
    service._execute_model_install(SimpleNamespace(execution_profile={'operation': 'runtime', 'model_id': 'sample'}), context)
    assert calls == ['sample']
