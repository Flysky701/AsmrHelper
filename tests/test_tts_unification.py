"""Unified TTS source and real Speech orchestration with offline generated audio."""
from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from click.testing import CliRunner
from src.app.errors import AppValidationError
from src.app.services.artifact_service import ArtifactService
from src.app.services.capability_descriptor_service import CapabilityDescriptorService
from src.app.services.execution_profile_builder import ExecutionProfileBuilder
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


def test_legacy_projection_tracks_provider_schema_and_never_reads_settings(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, 'get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('legacy config read')))
    service = CapabilityDescriptorService()
    providers = list_providers()
    descriptors = service.list_descriptors(category='tts')
    assert {d['provider'] for d in descriptors} == {p['provider_id'] for p in providers}
    for provider in providers:
        result = service.get_descriptor('tts', provider['provider_id'])
        assert result['supported_models'] == list(dict.fromkeys(m for mode in provider['modes'] for m in mode['models']))
        entries = {v['name']: v for v in result['common_option_schema'] + result['provider_option_schema']}
        for key, schema in provider['options_schema']['properties'].items():
            assert entries[key]['default'] == schema.get('default')
            assert entries[key]['min'] == schema.get('minimum')
            assert entries[key]['max'] == schema.get('maximum')


def test_builder_does_not_load_legacy_tts_settings():
    class NoSettings:
        def get_settings(self, **kwargs):
            raise AssertionError('legacy settings read')
    result = ExecutionProfileBuilder(settings_service=NoSettings()).build(category='tts')
    assert result['provider'] == 'edge'
    assert result['model'] == 'edge-tts'


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
        model='s2-pro', connection_ref=connection['id'], common_options={'voice': 'real-hosted-id'})
    assert result.engine == 'fish_audio'
    assert sf.info(result.output_path).format == 'FLAC'
    assert calls[0][1]['connection']['api_key'] == 'test-only'
    assert service.store.list('experiments')[0]['snapshot']['connection']['id'] == connection['id']
    assert 'api_key' not in service.store.list('experiments')[0]['snapshot']['connection']


def test_ambiguous_legacy_inputs_fail_before_synthesis(speech, tmp_path):
    service, calls = speech
    facade = TtsEngineService(speech_service=service)
    for kwargs in ({'provider': 'openai_compatible', 'model': 'model', 'common_options': {'voice': 'voice'}},
                   {'provider': 'qwen3', 'provider_options': {'voice_profile_id': 'old-id'}},
                   {'provider': 'voxcpm2', 'common_options': {'voice': 'unknown'}},
                   {'recipe_id': 'rule', 'connection_ref': 'connection'}):
        with pytest.raises(AppValidationError):
            facade.synthesize_text(text='Hello.', output_path=str(tmp_path / 'invalid.wav'), **kwargs)
    assert calls == []
    assert service.store.list('takes') == []


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


def test_pipeline_flat_adapter_keeps_model_and_provider_options(speech, monkeypatch):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService
    service, calls = speech
    facade = TtsEngineService(speech_service=service)
    monkeypatch.setattr('src.app.services.tts_engine_service.get_tts_engine_service', lambda: facade)
    request = PipelineRequest(input_path='input.wav', tts_engine='qwen3', tts_model='qwen3-custom-voice',
                              engine_params={'qwen3': {'temperature': .5}})
    stage = PipelineService._resolve_execution_profile(request)['stages']['tts']
    snapshot = service.pipeline_snapshot(stage)
    assert snapshot['recipe']['variant']['value'] == get_provider('qwen3').voice_sources('builtin')['default']
    assert snapshot['recipe']['provider_options']['temperature'] == .5
    request.voice_profile_id = 'historical-id'
    with pytest.raises(AppValidationError, match='Speech'):
        PipelineService._resolve_execution_profile(request)
    assert calls == []


@pytest.mark.parametrize('stage', [
    {'provider': 'edge', 'options': {'speed': 1.5, 'speech_source': {'provider_options': {'schema_version': 1, 'speed': .8}}}},
    {'provider': 'edge', 'options': {'speech_recipe_id': 'rule', 'voice': 'ignored'}},
    {'provider': 'edge', 'provider_options': {'proxy': 'ignored'}},
    {'provider': 'edge', 'options': {'voice': 'other', 'speech_source': {'variant': {'kind': 'builtin', 'value': 'zh-CN-XiaoxiaoNeural'}}}},
    {'provider': 'voxcpm2', 'options': {'voice': 'ignored'}},
    {'provider': 'qwen3', 'options': {'speed': 1.2}},
])
def test_snapshot_never_silently_discards_old_or_conflicting_parameters(speech, stage):
    service, calls = speech
    with pytest.raises(ValueError):
        service.pipeline_snapshot(stage)
    assert calls == []


def test_voice_and_speed_reach_compiled_request(speech, tmp_path):
    service, calls = speech
    TtsEngineService(speech_service=service).synthesize_text(text='声音。', output_path=str(tmp_path / 'options.wav'),
        provider='edge', common_options={'voice': 'zh-CN-YunxiNeural', 'speed': 1.4})
    params = calls[0][0]['parameters']
    assert params['variant']['value'] == 'zh-CN-YunxiNeural'
    assert params['options']['speed'] == 1.4


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
