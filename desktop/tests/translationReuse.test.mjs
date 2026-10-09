import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
function load(path) {
  const url = new URL(path, import.meta.url), module = { exports: {} }
  const { outputText } = ts.transpileModule(readFileSync(url, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  new Function('require', 'module', 'exports', outputText)(name => load(new URL(name + '.ts', url).href), module, module.exports)
  return module.exports
}
const { buildGraphRunRequest, newGraphNode } = load('../src/domain/workflowDraft.ts')

test('the explicit graph keeps translation with matching languages and freezes submitted data', () => {
  const graph = { version: 2, nodes: [], edges: [], input_slots: [{ id: 'text', type: 'subtitle', label: 'Text', language: 'zh' }], outputs: [{ node_id: 'export', port: 'subtitle' }] }
  const translate = { ...newGraphNode('translate', graph), source_lang: 'zh', target_lang: 'zh' }
  const output = newGraphNode('export', graph); output.options.subtitle_format = 'vtt'
  graph.nodes = [translate, output]
  graph.edges = [
    { source: { kind: 'slot', slot_id: 'text' }, target: { node_id: 'translate', port: 'subtitle' } },
    { source: { kind: 'node', node_id: 'translate', port: 'subtitle' }, target: { node_id: 'export', port: 'subtitle' } },
  ]
  const bindings = { text: { path: 'a.vtt', language: 'zh', language_confirmed: true } }
  const { execution_profile: profile } = buildGraphRunRequest(graph, bindings, ['a.vtt'])
  assert.deepEqual(profile.graph, graph)
  assert.deepEqual(profile.graph.nodes.map(node => node.kind), ['translate', 'export'])
  assert.equal(profile.graph.nodes[0].options.direct_tts, undefined)
  assert.equal(profile.graph.nodes[0].options.reuse_existing, undefined)
  assert.equal(profile.graph.nodes[1].options.subtitle_format, 'vtt')
  graph.nodes[0].target_lang = 'en'; bindings.text.path = 'edited.vtt'
  assert.equal(profile.graph.nodes[0].target_lang, 'zh')
  assert.equal(profile.bindings.text.path, 'a.vtt')
})
