"""Preset consumption uses local doubles; no cloud requests or model loading."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.app.services.speech_service import SpeechService
from src.core.speech.compiler import compile_recipe
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore, build_plan


@pytest.fixture
def speech(tmp_path, monkeypatch):
    service = SpeechService(store=SpeechStore(tmp_path / 'speech'), tasks=Mock(), dispatcher=Mock(), artifacts=Mock())
    for name in ('edge', 'qwen3', 'voxcpm2', 'fish_audio', 'openai_compatible'):
        monkeypatch.setattr(get_provider(name), 'probe', Mock(return_value={'ready': True}))
    return service


def save(speech, provider='edge', mode='builtin', model='edge-tts'):
    values = {'edge': 'en-US-JennyNeural', 'qwen3': 'Vivian', 'fish_audio': 'public-voice', 'voxcpm2': 'default', 'openai_compatible': 'voice'}
    variant = values[provider]
    if mode == 'reference':
        variant = speech.store.create('assets', {'sha256': 'a' * 64, 'transcript': 'hello', 'confirmed': True})['id']
    if mode == 'design':
        variant = 'A calm speaking voice'
    body = {'name': 'Saved voice', 'provider_id': provider, 'model': model, 'mode': mode,
            'variant': {'kind': mode, 'value': variant}, 'language': 'auto', 'provider_options': {'schema_version': 1}}
    if get_provider(provider).http:
        body['connection_ref'] = speech.save_connection({'name': 'Mock', 'provider_id': provider, 'deployment': 'cloud', 'base_url': 'https://example.invalid'})['id']
    return speech.save_rule(body)


def stage(recipe, overrides=None):
    return {'provider': recipe['provider_id'], 'model': recipe['model'], 'options': {'speech_recipe_id': recipe['id'], **({'speech_overrides': overrides} if overrides is not None else {})}}


def test_overrides_freeze_defaults_and_never_edit_saved_voice(speech):
    recipe = save(speech)
    original = deepcopy(recipe)
    request = stage(recipe, {'provider_options': {'speed': 1.4}, 'default_pause_ms': 350})
    snap = speech.pipeline_snapshot(request)
    assert snap['base_recipe'] == original
    assert snap['recipe']['id'] == original['id']
    assert snap['recipe']['provider_options']['speed'] == 1.4
    assert snap['speech_overrides']['default_pause_ms'] == 350
    assert speech.store.get('recipes', recipe['id']) == original
    assert len(speech.store.list('recipes')) == 1
    request['options']['speech_overrides']['provider_options']['speed'] = .5
    assert snap['speech_overrides']['provider_options']['speed'] == 1.4
    plan = build_plan('Hello.')
    plan['use_recipe_defaults'] = True
    compiled = compile_recipe(snap['recipe'], plan, snap['assets'])[0]
    assert compiled['parameters']['options']['speed'] == 1.4
    assert compiled['pause_ms'] == 350
    assert compiled['cache_key'] != compile_recipe(original, plan, {})[0]['cache_key']
    assert speech.pipeline_snapshot(stage(recipe))['recipe'] == original


@pytest.mark.parametrize('overrides', [
    {'variant': {'kind': 'hosted', 'value': 'other'}}, {'connection_ref': 'other'}, {'model': 'other'},
    {'language': 'ja'}, {'provider_id': 'fish_audio'}, {'provider_options': {'reference_id': 'other'}},
    {'provider_options': {'device': 'cpu'}}, {'provider_options': {'schema_version': 1}},
    {'provider_options': {'speed': True}}, {'provider_options': {'speed': 100}},
    {'provider_options': {'speed': float('nan')}}, {'provider_options': []}, [],
    {'default_pause_ms': True}, {'default_emotion': 'happy'}, {'default_delivery': 'whisper'},
])
def test_invalid_or_identity_overrides_are_rejected_without_writes(speech, overrides):
    recipe = save(speech)
    with pytest.raises(ValueError):
        speech.pipeline_snapshot(stage(recipe, overrides))
    assert speech.store.get('recipes', recipe['id']) == recipe


@pytest.mark.parametrize('provider,mode,model,option,value', [
    ('fish_audio', 'hosted', 's2-pro', 'speed', 1.2),
    ('fish_audio', 'hosted', 's2-pro', 'style_description', 'soft tone'),
    ('openai_compatible', 'hosted', 'custom', 'speed', 1.3),
    ('qwen3', 'builtin', 'qwen3-custom-voice', 'temperature', .8),
    ('qwen3', 'reference', 'qwen3-base', 'do_sample', False),
    ('qwen3', 'design', 'qwen3-voice-design', 'top_k', 25),
    ('voxcpm2', 'reference', 'voxcpm2', 'cfg_value', 1.5),
])
def test_each_supported_engine_mode_accepts_only_its_runtime_parameters(speech, provider, mode, model, option, value):
    recipe = save(speech, provider, mode, model)
    snap = speech.pipeline_snapshot(stage(recipe, {'provider_options': {option: value}}))
    assert snap['recipe']['provider_options'][option] == value
    assert snap['recipe']['variant'] == recipe['variant']


@pytest.mark.parametrize('provider,mode,model,overrides', [
    ('qwen3', 'reference', 'qwen3-base', {'provider_options': {'x_vector_only_mode': True}}),
    ('qwen3', 'design', 'qwen3-voice-design', {'provider_options': {'speed': 1.2}}),
    ('qwen3', 'reference', 'qwen3-base', {'default_emotion': 'happy'}),
    ('fish_audio', 'hosted', 's1', {'provider_options': {'style_description': 'soft'}}),
    ('fish_audio', 'hosted', 's1', {'provider_options': {'tag_density': 'full'}}),
    ('fish_audio', 'hosted', 's2-pro', {'default_emotion': 'invented'}),
])
def test_mode_specific_restrictions(speech, provider, mode, model, overrides):
    with pytest.raises(ValueError):
        speech.pipeline_snapshot(stage(save(speech, provider, mode, model), overrides))


def test_overrides_require_saved_recipe(speech):
    with pytest.raises(ValueError, match='已保存音色'):
        speech.pipeline_snapshot({'provider': 'edge', 'model': 'edge-tts', 'options': {'speech_overrides': {}}})


def test_descriptor_does_not_offer_reference_identity_controls():
    qwen = get_provider('qwen3').describe()
    assert all('x_vector_only_mode' not in mode['runtime_options'] for mode in qwen['modes'])
    assert get_provider('fish_audio').runtime_options('s1', 'hosted') == ['speed', 'temperature', 'top_p']


def test_graph_freezes_effective_voice_once_and_recovers_without_resolving_again(speech, monkeypatch):
    from src.app.services.graph_pipeline_service import freeze_graph_speech, node_profile
    from src.core.orchestration.pipeline.graph_catalog import GRAPH_OPTION_KEYS
    recipe = save(speech)
    node = {**stage(recipe, {'provider_options': {'speed': 1.3}}), 'kind': 'tts', 'id': 'tts', 'target_lang': 'zh', 'provider_options': {}}
    profile = {'graph': {'nodes': [node]}}
    monkeypatch.setattr('src.app.services.speech_service.get_speech_service', lambda: speech)
    frozen = freeze_graph_speech(profile)
    snap = frozen['_graph_runtime']['node_snapshots']['tts']
    assert 'speech_overrides' in GRAPH_OPTION_KEYS['tts']
    assert snap['recipe']['language'] == 'zh'
    assert snap['base_recipe']['language'] == 'auto'
    assert snap['recipe']['provider_options']['speed'] == 1.3
    assert speech.store.get('recipes', recipe['id']) == recipe
    monkeypatch.setattr(speech, 'pipeline_snapshot', Mock(side_effect=AssertionError('must use frozen snapshot')))
    recovered = freeze_graph_speech(frozen)
    assert recovered == frozen
    assert node_profile(node, snap)['stages']['tts']['provider_options']['speech_snapshot'] == snap
