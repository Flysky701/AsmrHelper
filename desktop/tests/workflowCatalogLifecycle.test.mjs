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
  new Function('require', 'module', 'exports', outputText)(name => name === '../api/pipeline' ? { pipelineApi: {} }
    : name.startsWith('.') ? load(new URL(name, url).href) : require(name), module, module.exports)
  return module.exports
}
const { createWorkflowStore, presetDeleteConfirmation } = load('../src/stores/workflowStore.ts')
const graph = { version: 2, nodes: [], edges: [], input_slots: [], outputs: [] }
const builtin = { id: 'shipped', label: 'Template', description: '', revision: 1, builtin: true, version: 2, graph }
function fixture(initial = [builtin]) {
  let items = structuredClone(initial), sequence = 0
  const calls = [], data = new Map()
  const storage = { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
  const client = {
    graphPresets: async () => ({ presets: structuredClone(items) }),
    builtinTemplates: async () => ({ presets: [structuredClone(builtin)] }),
    permanentlyDeletePreset: async id => { calls.push(['delete', id]); items = items.filter(item => item.id !== id); return { id, status: 'deleted' } },
    addBuiltinTemplate: async (id, revision, label) => {
      calls.push(['add', id]); const item = { ...structuredClone(builtin), id: `new-${++sequence}`, label: label || builtin.label, builtin: false }
      items.push(item); return item
    },
  }
  return { store: createWorkflowStore(client, storage), reopen: () => createWorkflowStore(client, storage), calls }
}

const starter = { ...builtin, id: 'starter_edge_chinese_v1', label: '中文配音演示', graph: {
  version: 2, nodes: [{ id: 'tts', kind: 'tts', provider: 'edge', model: 'edge-tts', target_lang: 'zh', options: {}, provider_options: {} }],
  edges: [{ source: { kind: 'slot', slot_id: 'subtitle' }, target: { node_id: 'tts', port: 'subtitle' } }],
  input_slots: [{ id: 'subtitle', type: 'subtitle', label: '中文字幕', language: 'zh' }],
  outputs: [{ node_id: 'tts', port: 'audio' }],
} }

test('blank workbench selects only the starter once and deletion survives restart', async () => {
  const f = fixture([starter, builtin]), s = f.store.getState()
  await s.loadCatalog()
  assert.equal(f.store.getState().selectedPreset.id, starter.id)
  assert.deepEqual(f.store.getState().runtimeGraph, starter.graph)
  await s.loadCatalog()
  const restarted = f.reopen(); await restarted.getState().loadCatalog()
  assert.deepEqual(restarted.getState().catalog.map(item => item.id), [starter.id, builtin.id])
  assert.equal(restarted.getState().selectedPreset.id, starter.id)
  assert.deepEqual(f.calls, [])
  assert.equal(await restarted.getState().deleteCatalogPreset(starter), 'deleted')
  const afterDelete = f.reopen(); await afterDelete.getState().loadCatalog()
  assert.equal(afterDelete.getState().selectedPreset, null)
  assert.deepEqual(afterDelete.getState().runtimeGraph, starter.graph)
  assert.deepEqual(afterDelete.getState().catalog.map(item => item.id), [builtin.id])
})

test('starter never replaces saved selection, parameters, bindings or drafts', async () => {
  const scenarios = [
    store => { store.getState().selectPreset(builtin); store.setState({ runtimeGraph: starter.graph }) },
    store => store.setState({ runtimeGraph: starter.graph }),
    store => store.getState().setBinding('subtitle', { path: 'my.zh.srt' }),
    store => { store.getState().openEditor(null, 'workbench'); store.getState().updateEditor({ label: 'My draft' }) },
    store => store.setState({ recoveryDraft: { unknown: 'preserve' } }),
    store => store.setState({ recoveryDraft: false }),
  ]
  for (const prepare of scenarios) {
    const f = fixture([starter, builtin]); prepare(f.store)
    const { selectedPreset, runtimeGraph, bindings, editor, recoveryDraft } = f.store.getState()
    await f.store.getState().loadCatalog()
    const after = f.store.getState()
    assert.deepEqual({ selectedPreset: after.selectedPreset, runtimeGraph: after.runtimeGraph,
      bindings: after.bindings, editor: after.editor, recoveryDraft: after.recoveryDraft },
    { selectedPreset, runtimeGraph, bindings, editor, recoveryDraft })
  }
})

test('absence of starter never selects a model flow or a custom preset with its ID', async () => {
  for (const items of [[builtin], [{ ...starter, builtin: false }, builtin]]) {
    const f = fixture(items); await f.store.getState().loadCatalog()
    assert.equal(f.store.getState().selectedPreset, null)
    assert.equal(f.store.getState().runtimeGraph, null)
  }
})

test('deleting a built-in preserves draft and bindings without a restore collection', async () => {
  const f = fixture(), s = f.store.getState()
  await s.loadCatalog(); await s.loadBuiltinTemplates()
  s.selectPreset(builtin); s.openEditor(builtin, 'settings'); s.updateEditor({ label: 'Unsaved edit' })
  s.setBinding('audio', { path: 'fixture.wav' })
  const runtime = structuredClone(f.store.getState().runtimeGraph)
  assert.equal(await s.deleteCatalogPreset(builtin), 'deleted')
  assert.deepEqual(f.calls, [['delete', 'shipped']])
  const after = f.store.getState()
  assert.equal(after.catalog.length, 0)
  assert.equal(after.selectedPreset, null)
  assert.equal(after.editor.preset, null)
  assert.equal(after.editor.label, 'Unsaved edit')
  assert.deepEqual(after.runtimeGraph, runtime)
  assert.equal(after.bindings.audio.path, 'fixture.wav')
  assert.equal(after.builtinTemplates.length, 1)
  assert.equal('restorePreset' in after, false)
  const restarted = f.reopen(); await restarted.getState().loadCatalog()
  assert.equal(restarted.getState().catalog.length, 0)
  assert.equal(restarted.getState().editor.label, 'Unsaved edit')
})

test('explicit template addition creates an independent entry without selecting or replacing drafts', async () => {
  const f = fixture(), s = f.store.getState()
  await s.loadCatalog(); await s.loadBuiltinTemplates(); s.openEditor(null, 'settings')
  s.updateEditor({ label: 'Current draft' })
  await s.deleteCatalogPreset(builtin)
  const added = await s.addBuiltinTemplate(builtin.id, builtin.revision, 'New preset')
  assert.notEqual(added.id, builtin.id)
  assert.equal(added.builtin, false)
  assert.equal(f.store.getState().selectedPreset, null)
  assert.equal(f.store.getState().editor.label, 'Current draft')
  assert.equal(f.store.getState().builtinTemplates.length, 1)
  assert.doesNotMatch(presetDeleteConfirmation(builtin), /可恢复/)
})
