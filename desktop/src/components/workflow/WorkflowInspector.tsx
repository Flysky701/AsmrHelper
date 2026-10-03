import type { ReactNode } from 'react'
import { GRAPH_CATALOG, type GraphDefinition, type GraphNode, type GraphEdge } from '@/domain/workflowGraph'
import { connectionChoices, PORT_NAMES, readSource, sourceKey, TYPE_NAMES } from './graphEditorModel'

export interface WorkflowInspectorProps {
  graph: GraphDefinition
  node: GraphNode | undefined
  issues: string[]
  onNodeChange: (node: GraphNode) => void
  onConnect: (target: GraphEdge['target'], source: GraphEdge['source'] | null) => void
  onOutput: (nodeId: string, port: string, selected: boolean) => void
  /** Integration supplies a node-controlled capability/voice form, never a shared singleton draft. */
  renderParameters: (node: GraphNode, onChange: (node: GraphNode) => void) => ReactNode
}
export function WorkflowInspector({ graph, node, issues, onNodeChange, onConnect, onOutput, renderParameters }: WorkflowInspectorProps) {
  if (!node) return <aside className="wg-inspector"><div className="wg-panel-heading"><span>节点设置</span></div><p className="wg-empty">选择节点，检查输入、参数与产出。</p></aside>
  const catalog = GRAPH_CATALOG[node.kind]
  return <aside className="wg-inspector" aria-label="节点设置">
    <div className="wg-panel-heading"><span>节点设置</span><small>{node.id}</small></div>
    <div className="wg-inspector-title"><div><h2>{catalog.label}</h2><p>每个实例独立配置</p></div></div>
    <section className="wg-inspector-delivery" aria-label="交付结果"><h3>交付结果</h3>{Object.entries(catalog.outputs).map(([port, type]) => <label className="wg-check" key={port}>
      <input type="checkbox" checked={graph.outputs.some(output => output.node_id === node.id && output.port === port)}
        onChange={event => onOutput(node.id, port, event.target.checked)} aria-label={`交付 ${node.id} ${port}`} />
      <span>{PORT_NAMES[port] || port}<small>{TYPE_NAMES[type]}</small></span>
    </label>)}<p className="wg-hint">勾选后显示在任务结果中；未勾选仍可供下游使用。</p></section>
    <div className="wg-inspector-scroll" role="region" aria-label={`${node.id} 参数与来源`} tabIndex={0}>
    <section><h3>输入来源</h3>{Object.entries(catalog.inputs).map(([port, type]) => {
      const edge = graph.edges.find(edge => edge.target.node_id === node.id && edge.target.port === port)
      const value = edge ? sourceKey(edge.source) : ''
      const options = connectionChoices(graph, node.id, type)
      return <label className="wg-field" key={port}><span>{PORT_NAMES[port] || port}<em>{TYPE_NAMES[type]}</em></span>
        <select aria-label={`${node.id} ${port} 来源`} value={value} onChange={event => onConnect({ node_id: node.id, port }, readSource(event.target.value))}>
          <option value="">请选择来源</option>
          {value && !options.some(option => option.value === value) && <option value={value}>原来源不可用</option>}
          {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
    })}<p className="wg-hint">可绑定输入槽或其他节点的兼容输出。没有来源时不会自动补跑前序。</p></section>
    <section><h3>参数</h3>{renderParameters(node, onNodeChange)}</section>
    {!!issues.length && <section className="wg-node-problems"><h3>需要补充</h3>{issues.map((issue, index) => <p key={index}>{issue}</p>)}</section>}
    </div>
  </aside>
}
