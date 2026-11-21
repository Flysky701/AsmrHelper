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
const consumption = load('../src/domain/speechPresetConsumption.ts')
const migration = load('../src/domain/speechPresetMigration.ts')
const graph = load('../src/domain/graphNodeParameters.ts')
const { useNavStore } = load('../src/stores/navStore.ts')
const { useSpeechPresetHandoffStore: handoff, openSpeechPresetLibrary } = load('../src/stores/speechPresetHandoffStore.ts')
const provider = { provider_id: 'qwen3', connection_required: false, capabilities: { pause: { support: 'postprocess' }, emotion: { support: 'unsupported' } },
  modes: [{ id: 'reference', models: ['qwen3-base'], variant_kinds: ['reference'], runtime_options: ['temperature'], voice_sources: { required: true, presets: [], allow_custom: false } }],
  options_schema: { properties: { temperature: { type: 'number', minimum: .01, maximum: 2, default: .9 }, x_vector_only_mode: { type: 'boolean', default: false, applies_to_modes: ['reference'] } } } }
const recipe = { id: 'saved', revision: 1, name: 'Reference voice', voice_id: 'voice', provider_id: 'qwen3', model: 'qwen3-base', mode: 'reference', connection_ref: 'engine-default-qwen3',
  language: 'auto', variant: { kind: 'reference', value: 'asset', style: 'normal' }, provider_options: { schema_version: 1, temperature: .9 }, default_pause_ms: 200 }
const node = { id: 'tts', kind: 'tts', provider: 'qwen3', model: 'qwen3-base', target_lang: 'zh', options: { speech_recipe_id: 'saved' }, provider_options: {} }

test('effective performance is detached and clearing an override restores the actual preset default', () => {
  const original = structuredClone(recipe)
  const changed = consumption.withSpeechOverrides(node, { provider_options: { temperature: .4 }, default_pause_ms: 400 })
  const effective = consumption.effectiveSpeechRecipe(recipe, changed.options.speech_overrides)
  assert.equal(effective.provider_options.temperature, .4)
  assert.deepEqual(recipe, original)
  assert.equal(consumption.withSpeechOverrides(changed, {}).options.speech_overrides, undefined)
  const cleared = consumption.withSpeechOverrides(changed, { default_pause_ms: undefined })
  assert.equal(consumption.effectiveSpeechRecipe(recipe, cleared.options.speech_overrides).default_pause_ms, 200)
})
test('reference identity and unsupported controls never enter runtime fields', () => {
  assert.deepEqual(consumption.runtimeSpeechOptions(provider, recipe).map(([key]) => key), ['temperature'])
  for (const patch of [{ variant: { value: 'other' } }, { provider_options: { x_vector_only_mode: true } }, { provider_options: { speed: 1.1 } }, { provider_options: null }, { default_emotion: 'happy' }, { provider_options: { temperature: 99 } }]) {
    assert.ok(consumption.speechOverrideIssue(provider, recipe, patch))
  }
})
test('legacy node becomes an independent preset while raw source and target language survive', () => {
  const legacy = graph.copyRecipeToGraphNode(node, recipe)
  const original = structuredClone(legacy)
  const result = migration.speechRecipeFromNode(legacy, [provider], [recipe])
  assert.equal(result.recipe.id, '')
  assert.equal(result.recipe.language, 'zh')
  assert.equal(result.recipe.variant.value, 'asset')
  assert.deepEqual(result.issues, [])
  assert.deepEqual(legacy, original)
  legacy.options.unknown = 9
  assert.ok(migration.speechRecipeFromNode(legacy, [provider], [recipe]).issues.length)
})
test('navigation rejection leaves handoff empty; successful handoff clones all unknown node data', async () => {
  handoff.setState({ pending: null, navigating: false })
  useNavStore.setState({ activePage: 'workbench', navigationGuard: () => false })
  assert.equal(await openSpeechPresetLibrary({ nodeDraft: node }), false)
  assert.equal(handoff.getState().pending, null)
  useNavStore.setState({ navigationGuard: () => true })
  const source = { ...structuredClone(node), options: { future: { preserve: true } } }
  assert.equal(await openSpeechPresetLibrary({ nodeDraft: source }), true)
  const pending = handoff.getState().pending
  source.options.future.preserve = false
  assert.equal(pending.nodeDraft.options.future.preserve, true)
  assert.equal(pending.returnTo, 'workbench')
  handoff.getState().acknowledge('unrelated')
  assert.equal(handoff.getState().pending.token, pending.token)
  handoff.getState().acknowledge(pending.token)
  assert.equal(handoff.getState().pending, null)
})
