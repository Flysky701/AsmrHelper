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
    {'variant': {'kind': 'hosted', 'value': 'other'}},
    {'connection_ref': 'other'},
    {'provider_options': {'device': 'cpu'}},
    {'provider_options': {'speed': 100}},
    {'default_delivery': 'whisper'},
])
def test_invalid_or_identity_overrides_are_rejected_without_writes(speech, overrides):
    recipe = save(speech)
    with pytest.raises(ValueError):
        speech.pipeline_snapshot(stage(recipe, overrides))
    assert speech.store.get('recipes', recipe['id']) == recipe


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
