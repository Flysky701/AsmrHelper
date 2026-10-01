import type { PointerEvent } from 'react'
import { GRAPH_CATALOG, type GraphDefinition, type GraphNode, type GraphEdge } from '@/domain/workflowGraph'
import { PORT_NAMES, TYPE_NAMES, sourceKey } from './graphEditorModel'

export interface WorkflowNodeProps {
  node: GraphNode
  graph: GraphDefinition
  selected: boolean
  issues: string[]
  pendingSource: GraphEdge['source'] | null
  onSelect: () => void
  onSource: (source: GraphEdge['source']) => void
  onTarget: (target: GraphEdge['target']) => void
  onMoveStart: (event: PointerEvent<HTMLElement>) => void
}

export function WorkflowNode({ node, graph, selected, issues, pendingSource, onSelect, onSource, onTarget, onMoveStart }: WorkflowNodeProps) {
  const catalog = GRAPH_CATALOG[node.kind]
  const hasOutput = graph.outputs.some(output => output.node_id === node.id)
  return <article className={`wg-node ${selected ? 'is-selected' : ''} ${issues.length ? 'has-issue' : ''}`} data-node-id={node.id} aria-label={`${catalog.label} ${node.id}`}>
    <button type="button" className="wg-node-heading" onClick={onSelect} onPointerDown={onMoveStart} aria-label={`配置 ${node.id}`}>
      <span className={`wg-module-icon kind-${node.kind}`} aria-hidden="true">{node.kind === 'tts' ? '♫' : node.kind === 'translate' ? '译' : node.kind === 'export' ? '↗' : node.kind === 'mix' ? '≋' : node.kind === 'asr' ? '文' : node.kind === 'align' ? '↔' : '∿'}</span>
      <span><strong>{catalog.label}</strong><small>{node.id}</small></span><span className="wg-node-drag" aria-hidden="true">⠿</span>
    </button>
    <div className="wg-node-ports">
      <div>{Object.entries(catalog.inputs).map(([port, type]) => {
        const connected = graph.edges.some(edge => edge.target.node_id === node.id && edge.target.port === port)
        return <button type="button" key={port} className={`wg-port input ${connected ? 'connected' : ''} ${pendingSource ? 'can-connect' : ''}`}
          data-endpoint={`target:${node.id}:${port}`} onClick={() => { onSelect(); onTarget({ node_id: node.id, port }) }}
          aria-label={`连接到 ${node.id} ${port}`} title={`${PORT_NAMES[port] || port} · ${TYPE_NAMES[type]}${connected ? ' · 已连接' : ' · 缺少来源'}`}>
          <i className={`wg-port-dot ${type}`} /><span>{PORT_NAMES[port] || port}</span>
        </button>
      })}</div>
      <div>{Object.entries(catalog.outputs).map(([port, type]) => {
        const source: GraphEdge['source'] = { kind: 'node', node_id: node.id, port }
        const armed = pendingSource && sourceKey(pendingSource) === sourceKey(source)
        return <button type="button" key={port} className={`wg-port output ${armed ? 'armed' : ''}`}
          data-endpoint={`source:${sourceKey(source)}`} onClick={() => onSource(source)}
          aria-label={`从 ${node.id} ${port} 连线`} title={`${PORT_NAMES[port] || port} · ${TYPE_NAMES[type]}，选择后点击目标输入`}>
          <span>{PORT_NAMES[port] || port}</span><i className={`wg-port-dot ${type}`} />
        </button>
      })}</div>
    </div>
    <button type="button" className="wg-node-summary" onClick={onSelect}>
      {node.kind === 'translate' ? `${node.source_lang || '?'} → ${node.target_lang || '?'}` : node.kind === 'tts' ? `声音参数 · ${String(node.options.voice || '待配置')}` : node.kind === 'export' ? `${String(node.options.subtitle_format || 'vtt').toUpperCase()} 文件` : node.kind === 'mix' ? '双音轨混合' : '查看节点参数'}
    </button>
    <footer className="wg-node-footer"><span className={issues.length ? 'wg-warning' : ''}>{issues.length ? `! ${issues.length} 项待补充` : '未运行'}</span>{hasOutput && <span className="wg-delivery-tag">交付</span>}</footer>
  </article>
}
