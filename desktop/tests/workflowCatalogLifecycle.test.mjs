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
function fixture() {
  let items = [structuredClone(builtin)], sequence = 0
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
