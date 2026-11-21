"""Unified TTS source and real Speech orchestration with offline generated audio."""
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from click.testing import CliRunner
from src.app.services.artifact_service import ArtifactService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.app.services.tts_engine_service import TtsEngineService
from src.core.speech.providers import get_provider, list_providers
from src.core.speech.store import SpeechStore


@pytest.fixture
def speech(tmp_path, monkeypatch):
    service = SpeechService(store=SpeechStore(tmp_path / 'library'), tasks=TaskService(), artifacts=ArtifactService())
    calls = []
    def synthesize(request, path, context, cancel):
        calls.append((deepcopy(request), deepcopy(context)))
        sf.write(path, np.sin(np.arange(2400) / 20).astype('float32') * .1, 24000)
        return {}
    for descriptor in list_providers():
        provider = get_provider(descriptor['provider_id'])
        monkeypatch.setattr(provider, 'probe', lambda context: {'ready': True})
        monkeypatch.setattr(provider, 'synthesize', synthesize)
    return service, calls


def test_cli_creates_real_audio_through_speech_runner(speech, tmp_path, monkeypatch):
    import src.cli as cli_module
    service, calls = speech
    monkeypatch.setattr(cli_module, 'get_tts_engine_service', lambda: TtsEngineService(speech_service=service))
    source, output = tmp_path / 'text.txt', tmp_path / 'output.wav'
    source.write_text('第一句。第二句。', encoding='utf-8')
    result = CliRunner().invoke(cli_module.cli, ['tts', '-i', str(source), '-o', str(output)])
    assert result.exit_code == 0, result.output
    assert sf.info(output).frames > 0
    assert len(calls) == 2
    assert ''.join(request['text'] for request, _ in calls) == source.read_text(encoding='utf-8')
    assert service.store.list('assemblies')
    assert all(Path(t['audio_path']).is_relative_to(tmp_path / 'speech') for t in service.store.list('takes'))


def test_named_connection_and_hosted_voice_are_explicit(speech, tmp_path):
    service, calls = speech
    connection = service.save_connection({'name': 'Fish', 'provider_id': 'fish_audio', 'deployment': 'cloud',
                                         'base_url': 'https://example.test/v1', 'api_key': 'test-only'})
    result = TtsEngineService(speech_service=service).synthesize_text(text='Hello.', output_path=str(tmp_path / 'fish.flac'),
        provider='fish_audio', model='drama-3', connection_ref=connection['id'],
        common_options={'voice': 'real-hosted-id'})
    assert result.engine == 'fish_audio'
    assert sf.info(result.output_path).format == 'FLAC'
    assert calls[0][1]['connection']['api_key'] == 'test-only'
    assert service.store.list('experiments')[0]['snapshot']['connection']['id'] == connection['id']
    assert 'api_key' not in service.store.list('experiments')[0]['snapshot']['connection']


def test_saved_rule_cli_uses_frozen_recipe_without_overrides(speech, tmp_path):
    service, calls = speech
    connection = service.save_connection({'name': 'Edge named', 'provider_id': 'edge', 'deployment': 'cloud'})
    voice = service.store.create('voices', {'name': 'Saved', 'bindings': []})
    rule = service.save_recipe({'name': 'Rule', 'voice_id': voice['id'], 'provider_id': 'edge', 'model': 'edge-tts',
        'mode': 'builtin', 'connection_ref': connection['id'],
        'variant': {'kind': 'builtin', 'value': 'zh-CN-XiaoxiaoNeural'},
        'provider_options': {'schema_version': 1, 'speed': 1.2}, 'language': 'zh'})
    result = TtsEngineService(speech_service=service).synthesize_text(text='规则试音。',
        output_path=str(tmp_path / 'rule.wav'), recipe_id=rule['id'])
    assert sf.info(result.output_path).frames > 0
    assert calls[0][0]['recipe_id'] == rule['id']
    assert calls[0][0]['parameters']['options']['speed'] == 1.2
    assert service.store.get('recipes', rule['id']) == rule


def test_cli_interrupt_cleans_incomplete_take_and_preserves_existing_output(speech, tmp_path, monkeypatch):
    service, calls = speech
    output = tmp_path / 'existing.wav'
    output.write_bytes(b'previous-output')
    def interrupted(request, path, context, cancel):
        path.write_bytes(b'partial-audio')
        raise KeyboardInterrupt()
    monkeypatch.setattr(get_provider('edge'), 'synthesize', interrupted)
    with pytest.raises(KeyboardInterrupt):
        TtsEngineService(speech_service=service).synthesize_text(text='中断。', output_path=str(output))
    assert output.read_bytes() == b'previous-output'
    assert service.store.list('takes') == []
    assert list((tmp_path / 'speech').rglob('*.wav')) == []
