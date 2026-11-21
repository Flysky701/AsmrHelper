import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const clone = value => JSON.parse(JSON.stringify(value))
const userLabel = '我的音轨 · Workbench {1}'
const userPath = 'C:/用户音频/音轨 · Workbench {1}.wav'

function harness() {
  const data = new Map(), cache = new Map()
  const storage = { getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
  globalThis.localStorage = storage
  function load(path) {
    let url = new URL(path, import.meta.url)
    if (!existsSync(url)) url = new URL(url.href + '.ts')
    if (cache.has(url.href)) return cache.get(url.href).exports
    const module = { exports: {} }; cache.set(url.href, module)
    const { outputText } = ts.transpileModule(readFileSync(url, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    })
    new Function('require', 'module', 'exports', outputText)(name => name.endsWith('/api/pipeline') ? { pipelineApi: {} }
      : name.startsWith('@/') ? load(new URL(`../src/${name.slice(2)}`, import.meta.url).href)
        : name.startsWith('.') ? load(new URL(name, url).href) : require(name), module, module.exports)
    return module.exports
  }
  return { load, storage, data,
    appearance: load('../src/stores/appearanceStore.ts'), i18n: load('../src/i18n.ts'),
    graphApi: load('../src/domain/workflowGraph.ts'), draft: load('../src/domain/workflowDraft.ts'),
    parameters: load('../src/domain/graphNodeParameters.ts'), editor: load('../src/components/workflow/graphEditorModel.ts'),
    workflow: load('../src/stores/workflowStore.ts') }
}

function audioGraph(h) {
  const difference = h.draft.newGraphNode('audio_difference', h.draft.emptyGraph())
  difference.options = { ...difference.options, alignment: 'auto', offset_ms: -12.5,
    gain_left: -.75, gain_right: 1.25, match_gain: true, calibration_end: 2.5 }
  let mix = h.parameters.addGraphMixTrack(h.draft.newGraphNode('mix', h.draft.emptyGraph()))
  mix = h.parameters.removeGraphMixTrack(mix, 'track_2')
  mix = h.parameters.addGraphMixTrack(mix)
  mix = h.parameters.updateGraphMixTrack(mix, 'track_3', { gain: .4, offset_ms: 125.5, muted: true })
  const slots = ['reference', 'mixed', 'effect', 'room']
  const graph = { version: 2, nodes: [difference, mix],
    input_slots: slots.map(id => ({ id, type: 'audio', label: `${userLabel} / ${id}` })),
    edges: [
      ...['reference', 'mixed'].map(port => ({ source: { kind: 'slot', slot_id: port }, target: { node_id: difference.id, port } })),
      { source: { kind: 'node', node_id: difference.id, port: 'audio' }, target: { node_id: mix.id, port: 'track_1' } },
      ...[['effect', 'track_3'], ['room', 'track_4']].map(([slot_id, port]) => ({ source: { kind: 'slot', slot_id }, target: { node_id: mix.id, port } })),
    ], outputs: [{ node_id: mix.id, port: 'audio', label: userLabel }, { node_id: difference.id, port: 'audio', label: '我的差分 {0}' }] }
  const paths = slots.map((id, index) => index ? `C:/用户音频/${id}.wav` : userPath)
  return { graph, paths, bindings: Object.fromEntries(slots.map((id, index) => [id, { path: paths[index] }])) }
}

test('audio template save and JSON catalog reload preserve dynamic ports, edges and user labels across locales', async () => {
  const h = harness(), { graph } = audioGraph(h)
  let catalogJson = '[]'
  const client = {
    createGraphPreset: async draft => {
      const item = { ...clone(draft), id: 'custom_audio_locale', revision: 1, builtin: false }
      catalogJson = JSON.stringify([item]); return clone(item)
    },
    graphPresets: async () => ({ presets: JSON.parse(catalogJson) }),
  }
  const store = h.workflow.createWorkflowStore(client, h.storage)
  store.getState().openEditor(null, 'workbench')
  store.getState().updateEditor({ graph, label: userLabel, description: 'Keep literal {0} and 中文' })
  h.appearance.useAppearanceStore.getState().setPreferences({ language: 'en' })
  const saved = await store.getState().saveEditor('copy')
  assert.ok(saved)
  assert.equal(saved.label, userLabel)
  assert.deepEqual(saved.graph, graph)
  h.appearance.useAppearanceStore.getState().setPreferences({ language: 'zh-CN' })
  const reloaded = h.workflow.createWorkflowStore(client, { getItem: () => null, setItem() {}, removeItem() {} })
  await reloaded.getState().loadCatalog()
  reloaded.getState().selectPreset(reloaded.getState().catalog[0])
  assert.deepEqual(reloaded.getState().runtimeGraph, graph)
  assert.deepEqual(reloaded.getState().runtimeGraph.edges, saved.graph.edges)
  assert.deepEqual(Object.keys(h.graphApi.graphNodeInputs(reloaded.getState().runtimeGraph.nodes[1])), ['track_1', 'track_3', 'track_4'])
  assert.deepEqual(h.graphApi.validateGraph(reloaded.getState().runtimeGraph), [])
  const removed = h.editor.updateNode(graph, h.parameters.removeGraphMixTrack(graph.nodes[1], 'track_3'))
  assert.equal(removed.edges.some(edge => edge.target.port === 'track_3'), false)
  assert.deepEqual(Object.keys(h.graphApi.graphNodeInputs(removed.nodes[1])), ['track_1', 'track_4'])
  assert.deepEqual(h.graphApi.validateGraph(removed), [])
})
