import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import WorkflowEditor from '@/components/workflow/WorkflowEditor'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { newGraphNode, emptyGraph } from '@/domain/workflowDraft'
import { validateGraph, type GraphDefinition } from '@/domain/workflowGraph'
import { addGraphMixTrack } from '@/domain/graphNodeParameters'
import '@/index.css'

const mix = addGraphMixTrack(newGraphNode('mix', emptyGraph()))
const difference = newGraphNode('audio_difference', emptyGraph())
const initial: GraphDefinition = {
  version: 2, nodes: [mix, difference],
  input_slots: [
    { id: 'original', type: 'audio', label: '基准音频 · 无附加音效' },
    { id: 'enhanced', type: 'audio', label: '同源音频 · 含附加音效' },
    { id: 'music', type: 'audio', label: '独立音乐素材' },
  ],
  edges: [
    { source: { kind: 'slot', slot_id: 'original' }, target: { node_id: difference.id, port: 'reference' } },
    { source: { kind: 'slot', slot_id: 'enhanced' }, target: { node_id: difference.id, port: 'mixed' } },
    { source: { kind: 'slot', slot_id: 'original' }, target: { node_id: mix.id, port: 'track_1' } },
    { source: { kind: 'slot', slot_id: 'music' }, target: { node_id: mix.id, port: 'track_2' } },
    { source: { kind: 'node', node_id: difference.id, port: 'audio' }, target: { node_id: mix.id, port: 'track_3' } },
  ], outputs: [{ node_id: mix.id, port: 'audio' }, { node_id: difference.id, port: 'audio' }],
}
const key = 'asmr-audio-modules-component-preview'
function Fixture() {
  const [graph, setGraph] = useState(initial)
  const [saved, setSaved] = useState('')
  const [workbench, setWorkbench] = useState(false)
  const issues = validateGraph(graph)
  return <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--bg-primary, #f4f6f3)' }}>
    <header style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0 }}>
      <strong>音频模块开发预览</strong><span>真实组件 · 示例图仅用于交互验证，没有执行结果</span>
      <button onClick={() => { localStorage.setItem(key, JSON.stringify(graph)); setSaved('示例图已保存到此预览专用草稿') }}>保存预览草稿</button>
      <button onClick={() => { const value = localStorage.getItem(key); if (value) { setGraph(JSON.parse(value)); setSaved('已重载预览草稿') } }}>重载预览草稿</button>
      <label><input type="checkbox" checked={workbench} onChange={event => setWorkbench(event.target.checked)} />工作台参数视图</label>
      <span role="status">{saved}</span>
    </header>
    {workbench ? <main style={{ overflow: 'auto', flex: 1, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
      {graph.nodes.map(node => <section key={node.id}><h2>{node.id}</h2><GraphNodeParameters node={node} onChange={next => setGraph(current => ({ ...current, nodes: current.nodes.map(item => item.id === next.id ? next : item) }))} /></section>)}
    </main> : <WorkflowEditor graph={graph} bindings={{}} materials={[]} templateMode issues={issues.map(issue => ({ message: issue.message, nodeId: issue.node_id }))}
      onChange={setGraph} onBindingsChange={() => {}} createNode={newGraphNode}
      renderParameters={(node, onChange) => <GraphNodeParameters node={node} onChange={onChange} allowStructureChanges />} />}
  </div>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
