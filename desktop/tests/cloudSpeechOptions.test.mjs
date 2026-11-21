import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url), cache = new Map()
function load(path) {
  let url = new URL(path, import.meta.url)
  if (!existsSync(url)) url = new URL(url.href + '.ts')
  if (cache.has(url.href)) return cache.get(url.href).exports
  const module = { exports: {} }; cache.set(url.href, module)
  const { outputText } = ts.transpileModule(readFileSync(url, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  new Function('require', 'module', 'exports', outputText)(name => name.startsWith('.') ? load(new URL(name, url).href)
    : name.startsWith('@/') ? load('../src/' + name.slice(2)) : require(name), module, module.exports)
  return module.exports
}

const options = load('../src/domain/speechAdvancedOptions.ts')
const connections = load('../src/domain/speechConnections.ts')
const consumption = load('../src/domain/speechPresetConsumption.ts')
const transitions = load('../src/domain/speechRecipeTransitions.ts')
const caps = { delivery: { normal: { support: 'direct' }, whisper: { support: 'unsupported' } }, emotion: { support: 'unsupported' }, languages: ['zh', 'en'], language_control: 'automatic' }
const provider = {
  provider_id: 'cloud', default_base_url: 'https://service.example/v1', capabilities: {},
  options_schema: { properties: {
    stability: { type: 'number', minimum: 0, maximum: 1, default: .5, model_overrides: { v3: { enum: [0, .5, 1] } } },
    speed: { type: 'number', default: 1, minimum: .7, maximum: 1.2, applies_to_models: ['flash'] },
    style: { type: 'number', default: 0, minimum: 0, maximum: 1, applies_to_modes: ['hosted'] },
  } },
  modes: [{ id: 'hosted', models: ['v3', 'flash'], variant_kinds: ['hosted'],
    capabilities: { ...caps, emotion: { support: 'direct' }, languages: ['zh', 'en', 'ja'] },
    model_capabilities: { flash: caps }, runtime_options: ['stability', 'style'], model_runtime_options: { flash: ['stability', 'speed'] },
  }],
}
const recipe = { ...transitions.blankSpeechRecipe(), provider_id: 'cloud', mode: 'hosted', model: 'v3', language: 'auto', variant: { kind: 'hosted', value: 'voice-id', style: 'normal' }, provider_options: { schema_version: 1, stability: .5 } }

test('changing a saved service provider starts a fresh connection with the provider defaults', () => {
  const current = { id: 'saved', name: 'Saved Fish', provider_id: 'fish_audio', api_key: 'old test key', credential_configured: true }
  const next = connections.speechConnectionDraftForProvider(current, { ...provider, connection_deployments: ['lan'] })
  assert.deepEqual(next, { name: '', provider_id: 'cloud', deployment: 'lan', base_url: 'https://service.example/v1', api_key: '' })
  assert.equal(current.provider_id, 'fish_audio')
})

test('Eleven v4 selection removes older model controls and preserves voice and connection', () => {
  const eleven = {
    provider_id: 'elevenlabs', capabilities: caps,
    options_schema: { properties: {
      speed: { type: 'number', default: 1, minimum: .7, maximum: 1.2, applies_to_models: ['eleven_flash_v2_5'] },
      stability: { type: 'number', default: .5, minimum: 0, maximum: 1, model_overrides: { eleven_v3: { enum: [0, .5, 1] } } },
      similarity_boost: { type: 'number', default: .75, minimum: 0, maximum: 1, applies_to_models: ['eleven_flash_v2_5', 'eleven_v4'] },
    } },
    modes: [{ id: 'hosted', models: ['eleven_v3', 'eleven_flash_v2_5', 'eleven_v4'], variant_kinds: ['hosted'],
      capabilities: caps, runtime_options: ['stability'],
      model_runtime_options: { eleven_v3: ['stability'], eleven_flash_v2_5: ['speed', 'stability', 'similarity_boost'], eleven_v4: ['stability', 'similarity_boost'] },
    }],
  }
  const original = { ...recipe, provider_id: 'elevenlabs', model: 'eleven_flash_v2_5', connection_ref: 'saved-connection',
    provider_options: { schema_version: 1, speed: .9, stability: .3 } }
  const v4 = transitions.selectSpeechModel(original, eleven, 'eleven_v4')
  assert.equal(v4.model, 'eleven_v4')
  assert.equal(v4.connection_ref, original.connection_ref)
  assert.deepEqual(v4.variant, original.variant)
  assert.deepEqual(v4.provider_options, { schema_version: 1, stability: .3 })
  assert.deepEqual(options.availableSpeechOptions(eleven, 'hosted', 'eleven_v4').map(([key]) => key), ['stability', 'similarity_boost'])
  assert.deepEqual(consumption.runtimeSpeechOptions(eleven, v4).map(([key]) => key), ['stability', 'similarity_boost'])
  assert.ok(options.speechOptionsIssue(eleven, 'hosted', { speed: 1 }, 'eleven_v4'))
  assert.deepEqual(consumption.runtimeSpeechOptions(eleven, original).map(([name]) => name), ['speed', 'stability', 'similarity_boost'])
  const v3 = transitions.selectSpeechModel(v4, eleven, 'eleven_v3')
  assert.deepEqual(v3.provider_options, { schema_version: 1 })
  assert.equal(original.provider_options.stability, .3)
})

const graph = load('../src/domain/graphNodeParameters.ts')
test('inline and saved graph nodes validate the chosen model language and emotion', () => {
  const source = { ...recipe, model: 'flash', language: 'auto', default_emotion: 'happy' }
  const node = { id: 'tts', kind: 'tts', provider: 'cloud', model: 'flash', target_lang: 'en', provider_options: {}, options: { speech_source: source } }
  assert.match(graph.graphSpeechIssue(node, provider, [], [], []), /情绪/)
  assert.match(graph.graphSpeechIssue({ ...node, target_lang: 'ja' }, provider, [], [], []), /目标语言/)
  const saved = { ...source, id: 'saved', revision: 1, default_emotion: 'neutral' }
  assert.match(graph.graphSpeechIssue({ ...node, target_lang: 'ja', options: { speech_recipe_id: 'saved' } }, provider, [saved], [], []), /目标语言/)
})
