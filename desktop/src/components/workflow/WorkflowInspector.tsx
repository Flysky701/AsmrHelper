import { t, format, useI18n } from '@/i18n'
import type { ReactNode } from 'react'
import { graphNodeInputs, graphInputLabel, GRAPH_CATALOG, type GraphDefinition, type GraphNode, type GraphEdge } from '@/domain/workflowGraph'
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
  useI18n()
  if (!node) return <aside className="wg-inspector"><div className="wg-panel-heading"><span>{t("节点设置")}</span></div><p className="wg-empty">{t("选择节点，检查输入、参数与产出。")}</p></aside>
  const catalog = GRAPH_CATALOG[node.kind]
  return <aside className="wg-inspector" aria-label={t("节点设置")}>
    <div className="wg-panel-heading"><span>{t("节点设置")}</span><small>{node.id}</small></div>
    <div className="wg-inspector-title"><div><h2>{t(catalog.label)}</h2></div></div>
    <section className="wg-inspector-delivery" aria-label={t("交付结果")}><h3>{t("交付结果")}</h3>{Object.entries(catalog.outputs).map(([port, type]) => <label className="wg-check" key={port}>
      <input type="checkbox" checked={graph.outputs.some(output => output.node_id === node.id && output.port === port)}
        onChange={event => onOutput(node.id, port, event.target.checked)} aria-label={format("交付 {0} {1}", [node.id, port])} />
      <span>{t(PORT_NAMES[port] || port)}<small>{t(TYPE_NAMES[type] || type)}</small></span>
    </label>)}</section>
    <div className="wg-inspector-scroll" role="region" aria-label={format("{0} 参数与来源", [node.id])} tabIndex={0}>
    <section><h3>{t("输入来源")}</h3>{Object.entries(graphNodeInputs(node)).map(([port, type]) => {
      const edge = graph.edges.find(edge => edge.target.node_id === node.id && edge.target.port === port)
      const value = edge ? sourceKey(edge.source) : ''
      const options = connectionChoices(graph, node.id, type)
      return <label className="wg-field" key={port}><span>{t(graphInputLabel(node, port))}<em>{t(TYPE_NAMES[type] || type)}</em></span>
        <select aria-label={format("{0} {1} 来源", [node.id, port])} value={value} onChange={event => onConnect({ node_id: node.id, port }, readSource(event.target.value))}>
          <option value="">{t("请选择来源")}</option>
          {value && !options.some(option => option.value === value) && <option value={value}>{t("原来源不可用")}</option>}
          {options.map(option => <option key={option.value} value={option.value}>{option.value.startsWith('node:') ? `${t(GRAPH_CATALOG[graph.nodes.find(item => item.id === option.value.split(':')[1])!.kind].label)} · ${option.value.split(':')[1]} / ${option.value.split(':')[2]}` : option.label}</option>)}
        </select>
      </label>
    })}</section>
    <section><h3>{t("参数")}</h3>{renderParameters(node, onNodeChange)}</section>
    {!!issues.length && <section className="wg-node-problems"><h3>{t("需要补充")}</h3>{issues.map((issue, index) => <p key={index}>{t(issue)}</p>)}</section>}
    </div>
  </aside>
}
