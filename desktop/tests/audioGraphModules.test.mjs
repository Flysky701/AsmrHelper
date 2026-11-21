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
  const { outputText } = ts.transpileModule(readFileSync(url, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  new Function('require', 'module', 'exports', outputText)(name => name.endsWith('/api/pipeline') ? { pipelineApi: {} }
    : name.startsWith('@/') ? load(new URL(`../src/${name.slice(2)}`, import.meta.url).href)
      : name.startsWith('.') ? load(new URL(name, url).href) : require(name), module, module.exports)
  return module.exports
}
const { validateGraph, graphNodeInputs } = load('../src/domain/workflowGraph.ts')
const { newGraphNode, emptyGraph, cloneDraft, buildGraphRunRequest } = load('../src/domain/workflowDraft.ts')
const { addGraphMixTrack, updateGraphMixTrack } = load('../src/domain/graphNodeParameters.ts')
const { connectPort, updateNode } = load('../src/components/workflow/graphEditorModel.ts')
const { graphBindingIssues } = load('../src/components/GraphRunBindings.tsx')
const { createWorkflowStore } = load('../src/stores/workflowStore.ts')
function graphFor(node) {
  const ports = Object.keys(graphNodeInputs(node))
  return { version: 2, nodes: [node], input_slots: ports.map(id => ({ id, label: id, type: 'audio' })),
    edges: ports.map(id => ({ source: { kind: 'slot', slot_id: id }, target: { node_id: node.id, port: id } })), outputs: [{ node_id: node.id, port: 'audio' }] }
}
const freshMix = () => newGraphNode('mix', emptyGraph())
const legacyMix = () => ({ ...freshMix(), options: { original_volume: .85, tts_volume_ratio: .5, tts_delay_ms: -20 } })

test('track edits survive serialization and build the existing execution request', () => {
  let node = addGraphMixTrack(freshMix())
  node = updateGraphMixTrack(node, 'track_2', { gain: .25, offset_ms: -12.5, muted: true })
  const graph = cloneDraft(graphFor(node)), paths = graph.input_slots.map(slot => `C:/fixtures/${slot.id}.wav`)
  const bindings = Object.fromEntries(graph.input_slots.map((slot, index) => [slot.id, { path: paths[index] }]))
  const request = buildGraphRunRequest(graph, bindings, paths)
  assert.deepEqual(validateGraph(graph), [])
  assert.deepEqual(request.execution_profile.graph, graph)
  assert.equal(request.execution_profile.graph.nodes[0].options.tracks[1].offset_ms, -12.5)
  assert.deepEqual(request.input.companion_paths, paths.slice(1))
})

test('workbench accepts independent audio for new mix but retains legacy timeline pairing', () => {
  for (const [node, needsPair] of [[freshMix(), false], [legacyMix(), true]]) {
    const graph = graphFor(node), items = graph.input_slots.map(slot => ({ path: `C:/fixtures/${slot.id}.wav` }))
    const bindings = Object.fromEntries(graph.input_slots.map((slot, index) => [slot.id, { path: items[index].path }]))
    const issues = graphBindingIssues(graph, bindings, items)
    assert.equal(issues.some(issue => issue.includes('同一录音和时间轴')), needsPair)
  }
})

test('workbench blocks track additions, removals and conversion while permitting sound parameters', () => {
  const store = createWorkflowStore({}, { getItem: () => null, setItem: () => {}, removeItem: () => {} })
  const node = freshMix(), graph = graphFor(node)
  store.setState({ runtimeGraph: graph })
  store.getState().updateRuntimeNode(addGraphMixTrack(node))
  assert.deepEqual(store.getState().runtimeGraph, graph)
  assert.ok(store.getState().error)
  store.getState().updateRuntimeNode(updateGraphMixTrack(node, 'track_1', { gain: .4 }))
  assert.equal(store.getState().runtimeGraph.nodes[0].options.tracks[0].gain, .4)
  store.getState().updateRuntimeNode(legacyMix())
  assert.ok(store.getState().error)
  assert.deepEqual(Object.keys(graphNodeInputs(store.getState().runtimeGraph.nodes[0])), ['track_1', 'track_2'])
})
