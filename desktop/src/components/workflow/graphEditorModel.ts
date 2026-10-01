import { GRAPH_CATALOG, type GraphDefinition, type GraphNode, type GraphNodeKind, type GraphEdge, type GraphBindings } from '@/domain/workflowGraph'

export interface WorkflowMaterial {
  id: string
  path: string
  name: string
  type: 'audio' | 'subtitle'
  language?: 'ja' | 'zh' | 'en'
  valid: boolean
}

export function sourceKey(source: GraphEdge['source']): string {
  return source.kind === 'slot' ? `slot:${source.slot_id}` : `node:${source.node_id}:${source.port}`
}
export function readSource(value: string): GraphEdge['source'] | null {
  const [kind, id, port] = value.split(':')
  if (kind === 'slot' && id) return { kind: 'slot', slot_id: id }
  if (kind === 'node' && id && port) return { kind: 'node', node_id: id, port }
  return null
}
export function sourceType(graph: GraphDefinition, source: GraphEdge['source']): string | undefined {
  if (source.kind === 'slot') return graph.input_slots.find(slot => slot.id === source.slot_id)?.type
  const node = graph.nodes.find(node => node.id === source.node_id)
  return node ? GRAPH_CATALOG[node.kind].outputs[source.port] : undefined
}
export function sourceLabel(graph: GraphDefinition, source: GraphEdge['source']): string {
  if (source.kind === 'slot') return graph.input_slots.find(slot => slot.id === source.slot_id)?.label || '已移除的输入槽'
  const node = graph.nodes.find(node => node.id === source.node_id)
  return node ? `${GRAPH_CATALOG[node.kind].label} · ${node.id} / ${source.port}` : '已移除的节点'
}
export function connectionChoices(graph: GraphDefinition, nodeId: string, type: string) {
  return [
    ...graph.input_slots.filter(slot => slot.type === type).map(slot => ({ value: `slot:${slot.id}`, label: slot.label })),
    ...graph.nodes.filter(node => node.id !== nodeId).flatMap(node => Object.entries(GRAPH_CATALOG[node.kind].outputs)
      .filter(([, outputType]) => outputType === type)
      .map(([port]) => ({ value: `node:${node.id}:${port}`, label: `${GRAPH_CATALOG[node.kind].label} · ${node.id} / ${port}` }))),
  ]
}
/** Reject cycles before applying an edge; a draft may still have other missing ports. */
export function wouldCycle(graph: GraphDefinition, edge: GraphEdge): boolean {
  if (edge.source.kind === 'slot') return false
  const goal = edge.source.node_id
  const stack = [edge.target.node_id]
  const visited = new Set<string>()
  while (stack.length) {
    const next = stack.pop()!
    if (next === goal) return true
    if (visited.has(next)) continue
    visited.add(next)
    graph.edges.filter(item => item.source.kind === 'node' && item.source.node_id === next)
      .forEach(item => stack.push(item.target.node_id))
  }
  return false
}
export function connectPort(graph: GraphDefinition, target: GraphEdge['target'], source: GraphEdge['source'] | null): { graph: GraphDefinition; error: string } {
  const targetNode = graph.nodes.find(node => node.id === target.node_id)
  if (!targetNode) return { graph, error: '目标节点已不存在' }
  const edges = graph.edges.filter(edge => edge.target.node_id !== target.node_id || edge.target.port !== target.port)
  if (!source) return { graph: { ...graph, edges }, error: '' }
  const candidate = { source, target }
  if (sourceType(graph, source) !== GRAPH_CATALOG[targetNode.kind].inputs[target.port]) return { graph, error: '端口类型不匹配；请选择同类型的来源' }
  if (wouldCycle({ ...graph, edges }, candidate)) return { graph, error: '这条连线会形成循环；请改选其他来源' }
  return { graph: { ...graph, edges: [...edges, candidate] }, error: '' }
}
export function removeNode(graph: GraphDefinition, id: string): GraphDefinition {
  return { ...graph, nodes: graph.nodes.filter(node => node.id !== id),
    edges: graph.edges.filter(edge => edge.target.node_id !== id && !(edge.source.kind === 'node' && edge.source.node_id === id)),
    outputs: graph.outputs.filter(output => output.node_id !== id) }
}
export function nextNodeId(graph: GraphDefinition, kind: GraphNodeKind): string {
  let count = 1
  while (graph.nodes.some(node => node.id.toLowerCase() === `${kind}_${count}`)) count++
  return `${kind}_${count}`
}
export function updateNode(graph: GraphDefinition, node: GraphNode): GraphDefinition {
  return { ...graph, nodes: graph.nodes.map(item => item.id === node.id ? node : item) }
}
export function bindingIssues(graph: GraphDefinition, bindings: GraphBindings, materials: WorkflowMaterial[]): string[] {
  return graph.input_slots.flatMap(slot => {
    const binding = bindings[slot.id]
    if (!binding) return [`${slot.label}：请选择素材`]
    const material = materials.find(item => item.path === binding.path)
    if (!material) return [`${slot.label}：原素材不在当前素材池，请重新指定`]
    if (!material.valid || material.type !== slot.type) return [`${slot.label}：素材无效或类型不匹配`]
    if (slot.type === 'subtitle') {
      const actual = material.language || (binding.language_confirmed ? binding.language : undefined)
      if (!actual) return [`${slot.label}：字幕语言未知，请明确确认`]
      if (slot.language && actual !== slot.language) return [`${slot.label}：素材语言与输入槽要求不同`]
    }
    return []
  })
}

export const PORT_NAMES: Record<string, string> = { audio: '音频', speech: '叠加音轨', subtitle: '字幕' }
export const TYPE_NAMES: Record<string, string> = { audio: 'Audio', subtitle: 'VTT / 字幕' }
