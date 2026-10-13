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
const { graphMixOutputLength, addGraphMixTrack, removeGraphMixTrack, updateGraphMixTrack } = load('../src/domain/graphNodeParameters.ts')
const { connectPort, updateNode } = load('../src/components/workflow/graphEditorModel.ts')
const { graphBindingIssues } = load('../src/components/GraphRunBindings.tsx')
const { createWorkflowStore } = load('../src/stores/workflowStore.ts')
const { taskExecutionView } = load('../src/domain/taskExecutionView.ts')
function graphFor(node) {
  const ports = Object.keys(graphNodeInputs(node))
  return { version: 2, nodes: [node], input_slots: ports.map(id => ({ id, label: id, type: 'audio' })),
    edges: ports.map(id => ({ source: { kind: 'slot', slot_id: id }, target: { node_id: node.id, port: id } })), outputs: [{ node_id: node.id, port: 'audio' }] }
}
const freshMix = () => newGraphNode('mix', emptyGraph())
const legacyMix = () => ({ ...freshMix(), options: { original_volume: .85, tts_volume_ratio: .5, tts_delay_ms: -20 } })

test('new mix is N-track longest; old templates retain dual ports, options and main duration', () => {
  const current = freshMix(), old = legacyMix()
  assert.deepEqual(Object.keys(graphNodeInputs(current)), ['track_1', 'track_2'])
  assert.equal(graphMixOutputLength(current), 'longest')
  assert.deepEqual(Object.keys(graphNodeInputs(old)), ['audio', 'speech'])
  assert.equal(graphMixOutputLength(old), 'main')
  assert.deepEqual(validateGraph(cloneDraft(graphFor(old))), [])
  assert.deepEqual(cloneDraft(graphFor(old)).nodes[0].options, old.options)
})

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

test('removing a middle track only removes its edge; new IDs do not renumber neighbours', () => {
  const node = addGraphMixTrack(freshMix()), graph = graphFor(node)
  const next = updateNode(graph, removeGraphMixTrack(node, 'track_2'))
  assert.deepEqual(next.nodes[0].options.tracks.map(track => track.id), ['track_1', 'track_3'])
  assert.deepEqual(next.edges.map(edge => edge.target.port), ['track_1', 'track_3'])
  assert.deepEqual(next.outputs, graph.outputs)
  assert.equal(addGraphMixTrack(next.nodes[0]).options.tracks.at(-1).id, 'track_4')
  assert.equal(removeGraphMixTrack({ ...node, options: { tracks: [{ id: 'only' }] } }, 'only').options.tracks.length, 1)
  assert.ok(connectPort(next, { node_id: node.id, port: 'track_2' }, { kind: 'slot', slot_id: 'track_1' }).error)
})

test('dynamic inputs require one compatible source each and reject invalid track definitions', () => {
  const graph = graphFor(freshMix())
  assert.ok(validateGraph({ ...graph, edges: graph.edges.slice(1) }).some(issue => issue.code === 'missing_input' && issue.port === 'track_1'))
  assert.ok(validateGraph({ ...graph, edges: [...graph.edges, graph.edges[0]] }).some(issue => issue.code === 'multiple_sources'))
  const wrongType = { ...graph, input_slots: graph.input_slots.map(slot => ({ ...slot, type: 'subtitle' })) }
  assert.ok(validateGraph(wrongType).some(issue => issue.code === 'type_mismatch'))
  for (const tracks of [[], Array.from({ length: 33 }, (_, index) => ({ id: `track_${index}` })), [{ id: 'same' }, { id: 'SAME' }], [{ id: '../bad' }], [{ id: 'a', gain: -1 }], [{ id: 'a', offset_ms: Infinity }], [{ id: 'a', muted: 'yes' }], null]) {
    assert.ok(validateGraph({ ...graph, nodes: [{ ...graph.nodes[0], options: { tracks } }] }).length)
  }
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

test('difference defaults work for short audio and retain signed manual values in auto mode', () => {
  const node = newGraphNode('audio_difference', emptyGraph())
  assert.equal(node.provider, 'local')
  assert.equal(node.options.calibration_end, undefined)
  assert.deepEqual(Object.keys(graphNodeInputs(node)), ['reference', 'mixed'])
  const graph = graphFor({ ...node, options: { ...node.options, alignment: 'auto', offset_ms: -4.5, gain_left: -1, gain_right: -.5, match_gain: true } })
  assert.deepEqual(validateGraph(cloneDraft(graph)), [])
  assert.equal(cloneDraft(graph).nodes[0].options.gain_left, -1)
  for (const patch of [{ calibration_start: 5, calibration_end: 3 }, { calibration_start: -1 }, { alignment: 'stretch' }, { alignment: null }, { alignment: ['manual'] }, { max_shift_seconds: 0 }, { max_shift_seconds: 31 }, { gain_left: NaN }, { match_gain: 'yes' }]) {
    assert.ok(validateGraph({ ...graph, nodes: [{ ...node, options: { ...node.options, ...patch } }] }).length)
  }
})

test('difference remains a recognizable graph step in task history', () => {
  const graph = graphFor(newGraphNode('audio_difference', emptyGraph()))
  const view = taskExecutionView({ params: { version: 2, graph }, status: 'completed', createdAt: 0 })
  assert.equal(view.source, 'graph')
  assert.equal(view.steps[0].state, 'completed')
  assert.match(view.steps[0].label, /音频差分/)
})
