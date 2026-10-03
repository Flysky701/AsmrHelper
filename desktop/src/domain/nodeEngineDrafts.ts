import type { GraphNode } from './workflowGraph'

/** Session-only drafts scoped by the mounted node editor; never serialized into a graph or recipe. */
export function restoreEngineDraft(current: GraphNode, candidate: GraphNode, drafts: Map<string, GraphNode>): GraphNode {
  drafts.set(current.provider, structuredClone(current))
  const saved = drafts.get(candidate.provider)
  if (!saved || saved.id !== current.id || saved.kind !== current.kind) return candidate
  return { ...current, provider: saved.provider, model: saved.model,
    options: structuredClone(saved.options), provider_options: structuredClone(saved.provider_options) }
}

/** Source-language/target-language belong to the node, never to a remembered engine draft. */
export function speechDraftKey(node: GraphNode): string {
  const source = node.options.speech_source as { mode?: unknown } | undefined
  return `${node.provider}:${node.model ?? ''}:${typeof source?.mode === 'string' ? source.mode : ''}`
}

export function restoreSpeechModeDraft(current: GraphNode, candidate: GraphNode, drafts: Map<string, GraphNode>): GraphNode {
  drafts.set(speechDraftKey(current), structuredClone(current))
  const saved = drafts.get(speechDraftKey(candidate))
  if (!saved || saved.id !== current.id) return candidate
  // Preserve a deliberate current connection selection while restoring mode-specific sound parameters.
  const currentSource = current.options.speech_source as { connection_ref?: string } | undefined
  const options = structuredClone(saved.options)
  if (currentSource?.connection_ref && options.speech_source && typeof options.speech_source === 'object') {
    options.speech_source = { ...options.speech_source, connection_ref: currentSource.connection_ref }
  }
  return { ...current, model: saved.model, options, provider_options: structuredClone(saved.provider_options) }
}
