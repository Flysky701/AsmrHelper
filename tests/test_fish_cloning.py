"""Offline contract tests; generated audio, fake credentials, all HTTP intercepted."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import numpy as np
import pytest
import soundfile as sf

from src.api.http.routes.speech import router
from src.app.services.speech_service import SpeechService, get_speech_service
from src.app.services.fish_clone_service import FishCloneService
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech import fish_cloning, providers
from src.core.speech.store import SpeechStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = SpeechStore(tmp_path / 'speech')
    speech = SpeechService(store=store, tasks=TaskService(), artifacts=ArtifactService())
    connection = store.create('connections', {'name': 'Test', 'provider_id': 'fish_audio',
        'deployment': 'cloud', 'base_url': 'https://api.fish.audio/v1'})
    source = tmp_path / 'generated.wav'
    sf.write(source, np.sin(np.arange(2400) / 20) * .1, 24000)
    asset = store.import_reference(source, 0, None, '测试原文', 'zh', confirmed=True, name='Synthetic')
    # Do not load credentials from any user configuration.
    monkeypatch.setattr(speech, 'connection_context', lambda conn: {'connection': {**conn, 'api_key': 'fake-test-key'}})
    state = {'status': 201, 'body': {'_id': 'remote-voice', 'state': 'created'}}
    requests = []

    def handle(request):
        requests.append(request)
        if state.get('timeout'):
            raise httpx.ReadTimeout('sensitive upstream detail', request=request)
        if request.url.path == '/wallet/self/package':
            return httpx.Response(200, json={'user_id': 'owner-id'})
        if request.url.path == '/v1/tts':
            return httpx.Response(200, content=source.read_bytes())
        return httpx.Response(state['status'], json=state['body'])

    real_client = httpx.Client
    fake_http = SimpleNamespace(Client=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
        Timeout=httpx.Timeout, RequestError=httpx.RequestError, TimeoutException=httpx.TimeoutException)
    monkeypatch.setattr(fish_cloning, 'httpx', fake_http)
    monkeypatch.setattr(providers, 'httpx', fake_http)
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    app.dependency_overrides[get_speech_service] = lambda: speech
    with TestClient(app) as client:
        yield SimpleNamespace(store=store, speech=speech, svc=FishCloneService(speech), client=client,
            connection=connection, asset=asset, state=state, requests=requests, root=tmp_path)


def draft(env):
    return {'connection_ref': env.connection['id'], 'asset_id': env.asset['id'], 'title': '我的音色'}


def submission(env):
    preview = env.svc.preview(draft(env))
    return {**draft(env), 'token': preview['token'], 'request_id': str(uuid4())}


def test_http_clone_status_save_compile_and_workbench(setup):
    env = setup
    def post(path, body=None, status=200):
        response = env.client.post('/api/v1/speech' + path, json=body)
        assert response.status_code == status, response.text
        return response.json()
    preview = post('/fish-clones/preview', draft(env))
    assert env.requests == []
    assert preview['endpoint'] == 'https://api.fish.audio/model'
    body = submission(env)
    clone = post('/fish-clones', body)
    assert clone['state'] == 'created'
    request = env.requests[0]
    assert request.url == 'https://api.fish.audio/model' and request.method == 'POST'
    assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
    content = request.content
    for name, value in [('type', 'tts'), ('train_mode', 'fast'), ('visibility', 'private'),
                        ('texts', '测试原文'), ('generate_sample', 'false'), ('enhance_audio_quality', 'false')]:
        assert f'name="{name}"\r\n\r\n{value}'.encode() in content
    assert b'name="voices"; filename="reference.wav"' in content
    assert b'RIFF' in content
    post('/fish-clones/' + clone['id'] + '/rule', status=422)
    env.state.update(status=200, body={'_id': 'remote-voice', 'state': 'trained'})
    refreshed = post('/fish-clones/' + clone['id'] + '/refresh')
    assert refreshed['state'] == 'trained'
    assert env.requests[-1].url.path == '/model/remote-voice'
    saved = post('/fish-clones/' + clone['id'] + '/rule')
    assert saved['model'] == 's2.1-pro-free'
    assert saved['variant'] == {'kind': 'hosted', 'value': 'remote-voice', 'style': 'normal'}
    assert post('/fish-clones/' + clone['id'] + '/rule')['id'] == saved['id']
    assert len(env.requests) == 2  # Save and workbench handoff do not synthesize.
    assert post('/workbench-draft', {'recipe_id': saved['id']})['recipe']['id'] == saved['id']
    plan = post('/plans', {'text': '新台词。'})
    compiled = post('/compile', {'recipe_id': saved['id'], 'plan_id': plan['id']})['requests'][0]
    providers.get_provider('fish_audio').synthesize(compiled, env.root / 'out.wav',
        env.speech.connection_context(env.connection), None)
    tts = env.requests[-1]
    assert tts.headers['model'] == 's2.1-pro-free'
    assert json.loads(tts.content)['reference_id'] == 'remote-voice'
    assert 'references' not in json.loads(tts.content)
    assert 'fake-test-key' not in env.store.path.read_text(encoding='utf-8')


@pytest.mark.parametrize('change', ['asset', 'connection', 'bytes', 'archived'])
def test_review_invalidated_before_upload(setup, change):
    env = setup
    body = submission(env)
    if change == 'asset':
        env.store.reference_metadata(env.asset['id'], {'name': 'Changed'})
    elif change == 'connection':
        env.store.update('connections', env.connection['id'], {'name': 'Changed'})
    elif change == 'bytes':
        from pathlib import Path
        with Path(env.asset['path']).open('ab') as f:
            f.write(b'changed')
    elif change == 'archived':
        state = env.store._read()
        state["collections"]["assets"][env.asset["id"]]["archived"] = True
        env.store._write(state)
    with pytest.raises(ValueError):
        env.svc.create(body)
    assert env.requests == []


def test_duplicate_creation_is_not_retried_even_after_restart(setup):
    body = submission(setup)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: setup.svc.create(body), range(2)))
    assert results[0]['id'] == results[1]['id']
    assert len(setup.requests) == 1
    assert FishCloneService(setup.speech).create(body)['id'] == results[0]['id']
    assert len(setup.requests) == 1


def test_unconfirmed_transcript_never_uploads(setup):
    unconfirmed = setup.store.import_reference(setup.root / 'generated.wav', 0, None, '', 'zh', confirmed=False)
    with pytest.raises(ValueError, match='已核对'):
        setup.svc.preview({**draft(setup), 'asset_id': unconfirmed['id']})
    assert setup.requests == []


@pytest.mark.parametrize('kind', ['timeout', 'invalid', 'crash'])
def test_uncertain_result_persists_and_never_claims_ready(setup, kind):
    body = submission(setup)
    if kind == 'timeout':
        setup.state['timeout'] = True
    elif kind == 'invalid':
        setup.state['body'] = {'_id': 'remote-voice', 'state': 'unexpected'}
    else:
        setup.store.create('fish_clones', {'id': body['request_id'], 'review_token': body['token'], 'state': 'submitting'})
    result = setup.svc.create(body)
    assert result['state'] == 'unknown'
    assert setup.svc.list()[0]['state'] == 'unknown'
    assert len(setup.requests) == (0 if kind == 'crash' else 1)


@pytest.mark.parametrize('base', [
    'https://proxy.invalid/v1',
])
def test_clone_rejects_unreviewed_destination(setup, base):
    setup.store.update('connections', setup.connection['id'], {'base_url': base})
    with pytest.raises(ValueError):
        setup.svc.preview(draft(setup))
    assert setup.requests == []


@pytest.mark.parametrize('state', ['trained', 'failed', 'unknown'])
def test_local_delete_preserves_remote_recipe_source_and_dedup(setup, state):
    env = setup
    env.state['body']['state'] = 'trained'
    body = submission(env)
    clone = env.svc.create(body)
    rule = env.svc.save_rule(clone['id'])
    env.store.update('fish_clones', clone['id'], {'state': state})
    from pathlib import Path
    asset_bytes = Path(env.asset['path']).read_bytes()
    source_bytes = (env.root / 'generated.wav').read_bytes()
    before = {key: env.store.list(key) for key in ('assets', 'recipes', 'voices', 'connections')}
    response = env.client.delete('/api/v1/speech/fish-clones/' + clone['id'] + '?confirmed=true')
    assert response.status_code == 200 and response.json()['deleted'] == clone['id']
    assert env.client.get('/api/v1/speech/fish-clones').json()['items'] == []
    assert env.store.list('fish_clones') == []
    with pytest.raises(ValueError):
        env.svc.create(body)
    assert len(env.requests) == 1
    assert {key: env.store.list(key) for key in before} == before
    assert env.store.get('recipes', rule['id'])['model'] == 's2.1-pro-free'
    assert Path(env.asset['path']).read_bytes() == asset_bytes
    assert (env.root / 'generated.wav').read_bytes() == source_bytes
    assert env.client.post('/api/v1/speech/fish-clones/' + clone['id'] + '/restore').status_code == 404
    assert len(env.svc.list()) == 0
    assert len(env.requests) == 1
