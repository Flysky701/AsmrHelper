import type { GraphPipelineRunRequest, GraphPresetItem } from '../api/types'
import { validateGraph, type GraphBindings, type GraphDefinition, type GraphNode, type GraphNodeKind } from './workflowGraph'

export interface WorkflowEditorDraft {
  preset: GraphPresetItem | null
  graph: GraphDefinition
  label: string
  description: string
  returnTo: 'workbench' | 'settings'
  initialFingerprint: string
  warnings?: string[]
}

export function cloneDraft<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }

/** Object key order is immaterial; node/edge order remains part of the saved draft. */
export function draftFingerprint(value: unknown): string {
  const ordered = (item: unknown): unknown => Array.isArray(item) ? item.map(ordered)
    : item && typeof item === 'object' ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => [key, ordered(child)])) : item
  return JSON.stringify(ordered(value))
}

export function editorDirty(editor: WorkflowEditorDraft | null): boolean {
  return !!editor && editor.initialFingerprint !== draftFingerprint({ graph: editor.graph, label: editor.label, description: editor.description })
}

export function runtimeDirty(selectedPreset: GraphPresetItem | null, runtimeGraph: GraphDefinition | null): boolean {
  return !!runtimeGraph && (!selectedPreset || draftFingerprint(runtimeGraph) !== draftFingerprint(selectedPreset.graph))
}

export function emptyGraph(): GraphDefinition { return { version: 2, nodes: [], edges: [], input_slots: [], outputs: [] } }

export function newGraphNode(kind: GraphNodeKind, graph: GraphDefinition): GraphNode {
  const used = new Set(graph.nodes.map(node => node.id.toLowerCase()))
  let id = kind as string, suffix = 2
  while (used.has(id.toLowerCase())) id = `${kind}_${suffix++}`
  const defaults: Record<GraphNodeKind, [string, string | null]> = {
    separate: ['demucs', 'htdemucs'], asr: ['faster_whisper', 'faster-whisper-base'],
    align: ['qwen3_forced_aligner', 'qwen3-forced-aligner-0.6b'], translate: ['deepseek', null],
    tts: ['speech', null], mix: ['ffmpeg', null], export: ['ffmpeg', null],
  }
  const [provider, model] = defaults[kind]
  return { id, kind, provider, model,
    source_lang: ['asr', 'align', 'translate'].includes(kind) ? 'ja' : null,
    target_lang: ['translate', 'tts'].includes(kind) ? 'zh' : null,
    options: kind === 'export' ? { subtitle_format: 'srt' } : {}, provider_options: {} }
}

export function buildGraphRunRequest(graph: GraphDefinition, bindings: GraphBindings, inputPaths: string[], outputDirectory?: string): GraphPipelineRunRequest {
  const issues = validateGraph(graph)
  if (issues.length) throw new Error(issues.map(issue => issue.message).join('；'))
  const usedSlots = new Set(graph.edges.flatMap(edge => edge.source.kind === 'slot' ? [edge.source.slot_id] : []))
  const selectedPaths = new Set(inputPaths.map(pathKey))
  const paths: string[] = [], usedBindings: GraphBindings = {}
  const addPath = (path: string) => { if (!paths.some(item => pathKey(item) === pathKey(path))) paths.push(path) }
  for (const slot of graph.input_slots.filter(item => usedSlots.has(item.id))) {
    const binding = bindings[slot.id]
    if (!binding?.path?.trim()) throw new Error(`请为「${slot.label}」选择素材`)
    if (!selectedPaths.has(pathKey(binding.path))) throw new Error(`「${slot.label}」绑定的素材已不在当前输入中，请重新选择`)
    // File inspection can establish language without a manual confirmation. The
    // backend verifies that evidence; never manufacture language_confirmed here.
    if (slot.type === 'subtitle' && !binding.language) throw new Error(`请确认「${slot.label}」的字幕语言`)
    if (slot.language && binding.language && slot.language !== binding.language) throw new Error(`「${slot.label}」需要 ${slot.language} 素材，当前为 ${binding.language}`)
    if (binding.audio_path && (!selectedPaths.has(pathKey(binding.audio_path)) || binding.pair_confirmed !== true)) throw new Error(`请添加并确认「${slot.label}」对应的音频`)
    usedBindings[slot.id] = cloneDraft(binding)
    addPath(binding.path)
    if (binding.audio_path) addPath(binding.audio_path)
  }
  if (!paths.length) throw new Error('流水线没有已绑定的输入素材')
  return { input: { path: paths[0]!, companion_paths: paths.slice(1) }, output: { ...(outputDirectory?.trim() ? { directory: outputDirectory.trim() } : {}) },
    execution_profile: { version: 2, graph: cloneDraft(graph), bindings: usedBindings } }
}

function pathKey(path: string): string { return path.trim().replace(/\\/g, '/').toLowerCase() }
