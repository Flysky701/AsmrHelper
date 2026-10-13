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

test('model schema resolves enum, ranges and applicability without changing shared descriptors', () => {
  const original = structuredClone(provider)
  const fields = options.availableSpeechOptions(provider, 'hosted', 'v3')
  assert.deepEqual(fields.map(([name]) => name), ['stability', 'style'])
  assert.deepEqual(fields[0][1].enum, [0, .5, 1])
  assert.ok(options.speechOptionsIssue(provider, 'hosted', { stability: .3 }, 'v3'))
  assert.equal(options.speechOptionsIssue(provider, 'hosted', { stability: .3 }, 'flash'), '')
  assert.ok(options.speechOptionsIssue(provider, 'hosted', { speed: 1.5 }, 'flash'))
  assert.ok(options.speechOptionsIssue(provider, 'hosted', { speed: 1 }, 'v3'))
  assert.deepEqual(provider, original)
})
test('model runtime allowlist and capability overrides prevent unsupported task controls', () => {
  const flash = { ...recipe, model: 'flash' }
  assert.deepEqual(consumption.runtimeSpeechOptions(provider, flash).map(([name]) => name), ['stability', 'speed'])
  assert.ok(consumption.speechOverrideIssue(provider, flash, { default_emotion: 'happy' }))
  assert.ok(consumption.speechOverrideIssue(provider, flash, { provider_options: { style: .3 } }))
  assert.equal(consumption.speechOverrideIssue(provider, flash, { provider_options: { speed: 1.1 } }), '')
  assert.equal(consumption.speechOverrideIssue(provider, recipe, { default_emotion: 'happy' }), '')
})
test('model switching keeps identity and resets incompatible performance and parameter values', () => {
  const original = { ...recipe, default_emotion: 'happy', provider_options: { schema_version: 1, stability: .3, speed: 1.1 } }
  const v3 = transitions.selectSpeechModel(original, provider, 'v3')
  assert.equal(v3.provider_options.stability, .5)
  assert.equal(v3.provider_options.speed, undefined)
  const flash = transitions.selectSpeechModel(original, provider, 'flash')
  assert.equal(flash.default_emotion, 'neutral')
  assert.equal(flash.variant.value, 'voice-id')
  assert.equal(original.default_emotion, 'happy')
})
test('explicit language limits block unsupported saved language without erasing it', () => {
  const invalid = { ...recipe, model: 'flash', language: 'ja' }
  assert.ok(transitions.speechRecipeCapabilityIssue(invalid, provider))
  assert.equal(invalid.language, 'ja')
  assert.equal(options.speechLanguageSupported(provider, 'hosted', 'flash', 'auto'), true)
  assert.equal(options.speechLanguageSupported(provider, 'hosted', 'flash', 'zh'), true)
  assert.equal(options.speechLanguageSupported(provider, 'hosted', 'flash', 'ja'), false)
  assert.equal(options.speechLanguageSupported(provider, 'hosted', 'v3', 'ja'), true)
})
test('legacy descriptors and Fish default address retain their behavior', () => {
  const legacy = structuredClone(provider)
  delete legacy.modes[0].model_capabilities
  delete legacy.modes[0].model_runtime_options
  assert.equal(options.speechCapabilities(legacy, 'hosted', 'flash').emotion.support, 'direct')
  assert.deepEqual(consumption.runtimeSpeechOptions(legacy, recipe).map(([name]) => name), ['stability', 'style'])
  assert.equal(options.speechProviderBaseUrl(provider), 'https://service.example/v1')
  assert.equal(options.speechProviderBaseUrl({ provider_id: 'fish_audio' }), 'https://api.fish.audio/v1')
  assert.equal(options.speechProviderBaseUrl(undefined), '')
  assert.deepEqual(transitions.referenceModes(provider), [])
})

const graph = load('../src/domain/graphNodeParameters.ts')
const copy = load('../src/locales/voices.ts')
test('inline and saved graph nodes validate the chosen model language and emotion', () => {
  const source = { ...recipe, model: 'flash', language: 'auto', default_emotion: 'happy' }
  const node = { id: 'tts', kind: 'tts', provider: 'cloud', model: 'flash', target_lang: 'en', provider_options: {}, options: { speech_source: source } }
  assert.match(graph.graphSpeechIssue(node, provider, [], [], []), /情绪/)
  assert.match(graph.graphSpeechIssue({ ...node, target_lang: 'ja' }, provider, [], [], []), /目标语言/)
  const saved = { ...source, id: 'saved', revision: 1, default_emotion: 'neutral' }
  assert.match(graph.graphSpeechIssue({ ...node, target_lang: 'ja', options: { speech_recipe_id: 'saved' } }, provider, [saved], [], []), /目标语言/)
})
test('static cloud labels translate while arbitrary identifiers and backend text stay intact', () => {
  assert.equal(copy.speechProviderText('Stability'), '稳定度')
  assert.equal(copy.voiceMessages[copy.speechProviderText('Stability')], 'Stability')
  assert.equal(copy.speechProviderText('voice_private_123'), 'voice_private_123')
  assert.equal(copy.speechProviderText('Custom server message'), 'Custom server message')
})
