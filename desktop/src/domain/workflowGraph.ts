/** Graph V2 is the only execution authority. Runtime material bindings are separate. */
export const GRAPH_NODE_KINDS = ['separate', 'asr', 'align', 'translate', 'tts', 'mix', 'export', 'audio_export'] as const
/** Legacy kinds stay readable; the library offers only useful processing steps. */
export const GRAPH_ADDABLE_NODE_KINDS = GRAPH_NODE_KINDS.filter(kind => kind !== 'audio_export')
export type GraphNodeKind = (typeof GRAPH_NODE_KINDS)[number]
export type GraphLanguage = 'ja' | 'zh' | 'en'
export type GraphPortType = 'audio' | 'subtitle'
export const GRAPH_MIX_OUTPUT_LENGTHS = ['main', 'longest'] as const
export type GraphMixOutputLength = (typeof GRAPH_MIX_OUTPUT_LENGTHS)[number]
export interface GraphNode {
  id: string
  kind: GraphNodeKind
  provider: string
  model: string | null
  source_lang?: GraphLanguage | null
  target_lang?: GraphLanguage | null
  options: Record<string, unknown>
  provider_options: Record<string, unknown>
}
export interface GraphInputSlot {
  id: string
  type: GraphPortType
  label: string
  language?: GraphLanguage | null
}
export type GraphSource = { kind: 'slot'; slot_id: string } | { kind: 'node'; node_id: string; port: string }
export interface GraphTarget { node_id: string; port: string }
export interface GraphEdge { source: GraphSource; target: GraphTarget }
export interface GraphOutput extends GraphTarget { label?: string | null }
export interface GraphDefinition {
  version: 2
  nodes: GraphNode[]
  edges: GraphEdge[]
  input_slots: GraphInputSlot[]
  outputs: GraphOutput[]
}
export interface GraphMaterialBinding {
  path: string
  language?: GraphLanguage | null
  language_confirmed?: boolean
  audio_path?: string | null
  pair_confirmed?: boolean
  sha256?: string | null
}
export type GraphBindings = Record<string, GraphMaterialBinding>
export interface GraphExecutionProfile { version: 2; graph: GraphDefinition; bindings: GraphBindings }
export interface GraphIssue { code: string; message: string; node_id?: string; port?: string; slot_id?: string }
export interface GraphCapability {
  label: string
  inputs: Record<string, GraphPortType>
  outputs: Record<string, GraphPortType>
}
export const GRAPH_CATALOG: Record<GraphNodeKind, GraphCapability> = {
  separate: { label: '人声分离', inputs: { audio: 'audio' }, outputs: { audio: 'audio' } },
  asr: { label: '语音识别', inputs: { audio: 'audio' }, outputs: { subtitle: 'subtitle' } },
  align: { label: '时间轴校准', inputs: { audio: 'audio', subtitle: 'subtitle' }, outputs: { subtitle: 'subtitle' } },
  translate: { label: '字幕翻译', inputs: { subtitle: 'subtitle' }, outputs: { subtitle: 'subtitle' } },
  tts: { label: '语音合成', inputs: { subtitle: 'subtitle' }, outputs: { audio: 'audio' } },
  mix: { label: '混音', inputs: { audio: 'audio', speech: 'audio' }, outputs: { audio: 'audio' } },
  export: { label: '字幕格式转换', inputs: { subtitle: 'subtitle' }, outputs: { subtitle: 'subtitle' } },
  audio_export: { label: '音频导出', inputs: { audio: 'audio' }, outputs: { audio: 'audio' } },
}
export const GRAPH_OPTION_KEYS: Record<GraphNodeKind, readonly string[] | null> = {
  separate: ['mode'], asr: null, align: [], translate: null,
  tts: ['speech_recipe_id', 'speech_source', 'voice', 'speed'],
  mix: ['original_volume', 'tts_volume_ratio', 'tts_delay_ms', 'output_length'], export: ['subtitle_format'], audio_export: [],
}
const languages = new Set(['ja', 'zh', 'en'])
const identifier = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
const forbidden = new Set([
  'api_key', 'apikey', 'credential', 'credentials', 'credential_ref', 'token', 'password', 'authorization',
  'headers', 'secret', 'secrets', 'access_token', 'refresh_token', 'speech_snapshot', 'snapshot',
  'node_snapshots', 'runtime', 'bindings', 'asset_identity', 'path', 'audio_path', 'reference_path',
  'reference_audio', 'model_path', 'output_dir',
])
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}
function portableIssue(value: unknown, depth = 0): boolean {
  if (depth > 16) return true
  if (Array.isArray(value)) return value.some(item => portableIssue(item, depth + 1))
  if (record(value)) return Object.entries(value).some(([key, item]) => {
    const normalized = key.toLowerCase().replace(/-/g, '_')
    return forbidden.has(normalized) || normalized.endsWith('_path') || portableIssue(item, depth + 1)
  })
  if (typeof value === 'string') return /^(?:[A-Za-z]:[\\/]|[\\/]|file:|data:|https?:\/\/[^/]*@)/i.test(value)
  return value !== null && value !== undefined && !['string', 'number', 'boolean'].includes(typeof value)
    || typeof value === 'number' && !Number.isFinite(value)
}

/** Stable topology uses saved node order to break ties; never creates edges. */
export function topologicalNodeIds(graph: GraphDefinition): string[] {
  const dependencies = new Map(graph.nodes.map(node => [node.id, new Set<string>()]))
  for (const edge of graph.edges) {
    if (edge.source.kind === 'node') dependencies.get(edge.target.node_id)?.add(edge.source.node_id)
  }
  const order: string[] = [], done = new Set<string>()
  while (order.length < graph.nodes.length) {
    const next = graph.nodes.find(node => !done.has(node.id)
      && [...(dependencies.get(node.id) ?? [])].every(id => done.has(id)))
    if (!next) throw new Error('节点连线存在循环')
    done.add(next.id)
    order.push(next.id)
  }
  return order
}

/** Editor feedback only. The backend repeats authoritative validation before submission. */
export function validateGraph(graph: GraphDefinition): GraphIssue[] {
  const issues: GraphIssue[] = []
  const add = (code: string, message: string, node_id?: string, port?: string) => issues.push({ code, message, node_id, port })
  if (!record(graph) || graph.version !== 2 || Object.keys(graph).some(key => !['version', 'nodes', 'edges', 'input_slots', 'outputs'].includes(key))
      || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges) || !Array.isArray(graph.input_slots) || !Array.isArray(graph.outputs)) {
    return [{ code: 'invalid_graph', message: '图定义格式无效' }]
  }
  if (!graph.nodes.length || graph.nodes.length > 64 || graph.edges.length > 256 || graph.input_slots.length > 64
      || !graph.outputs.length || graph.outputs.length > 128) add('invalid_graph', '请添加节点和产出，并将图保持在支持的大小以内')
  const nodes = new Map<string, GraphNode>(), slots = new Map<string, GraphInputSlot>()
  for (const node of graph.nodes) {
    if (!record(node) || typeof node.id !== 'string' || !identifier.test(node.id) || [...nodes.keys()].some(id => id.toLowerCase() === node.id.toLowerCase())) { add('duplicate_or_invalid_id', '节点编号无效或重复'); continue }
    if (!GRAPH_NODE_KINDS.includes(node.kind)) { add('unknown_kind', '未知节点能力', node.id); continue }
    nodes.set(node.id, node)
    if (Object.keys(node).some(key => !['id', 'kind', 'provider', 'model', 'source_lang', 'target_lang', 'options', 'provider_options'].includes(key))) add('invalid_node', '节点包含未知字段', node.id)
    if (typeof node.provider !== 'string' || !node.provider.trim()) add('missing_provider', '请选择节点使用的引擎', node.id)
    if (node.model !== null && typeof node.model !== 'string') add('invalid_model', '模型必须是名称或空值', node.id)
    for (const language of [node.source_lang, node.target_lang]) if (language != null && !languages.has(language)) add('invalid_language', '语言仅支持 ja、zh、en', node.id)
    if (['asr', 'align', 'translate'].includes(node.kind) && !languages.has(node.source_lang ?? '')) add('missing_language', '请选择节点源语言', node.id)
    if (['tts', 'translate'].includes(node.kind) && !languages.has(node.target_lang ?? '')) add('missing_language', '请选择节点目标语言', node.id)
    for (const value of [node.options, node.provider_options]) {
      if (!record(value)) add('invalid_options', '节点参数必须是对象', node.id)
      else if (['language', 'source_lang', 'target_lang'].some(key => key in value)) add('duplicate_language', '请仅通过节点语言字段指定语言', node.id)
      if (portableIssue(value)) add('nonportable_parameter', '图参数不能包含路径、密钥或运行快照', node.id)
    }
    if (portableIssue(node.model)) add('nonportable_parameter', '模型请选择名称，不能在模板中保存路径', node.id)
    if (portableIssue(node.provider)) add('nonportable_parameter', '引擎请选择名称，不能保存路径', node.id)
    const allowed = GRAPH_OPTION_KEYS[node.kind]
    if (allowed && record(node.options) && Object.keys(node.options).some(key => !allowed.includes(key))) add('unsupported_option', '节点包含当前能力不会执行的参数', node.id)
    if (!['asr', 'translate'].includes(node.kind) && record(node.provider_options) && Object.keys(node.provider_options).length) add('unsupported_option', '该节点不接收顶层 provider_options', node.id)
    const fixed = ({ separate: 'demucs', align: 'qwen3_forced_aligner', mix: 'ffmpeg', export: 'ffmpeg', audio_export: 'local' } as Partial<Record<GraphNodeKind, string>>)[node.kind]
    if (fixed && node.provider !== fixed) add('unsupported_provider', `该能力当前仅接线 ${fixed}`, node.id)
    if (node.kind === 'align' && ![null, 'default', 'qwen3-forced-aligner-0.6b'].includes(node.model)) add('unsupported_model', '校准仅支持 qwen3-forced-aligner-0.6b', node.id)
    if (['mix', 'export', 'audio_export'].includes(node.kind) && ![null, 'default'].includes(node.model)) add('unsupported_model', '该节点不使用模型', node.id)
    if (node.kind === 'separate' && record(node.options) && (node.options.mode ?? 'vocals') !== 'vocals') add('unsupported_option', '分离节点当前仅提供人声轨', node.id)
    if (node.kind === 'mix' && record(node.options)) for (const [key, value] of Object.entries(node.options)) {
      if (['original_volume', 'tts_volume_ratio', 'tts_delay_ms'].includes(key) && (typeof value !== 'number' || !Number.isFinite(value) || key !== 'tts_delay_ms' && value < 0)) add('invalid_option', '混音参数必须是有效数值，音量不能为负数', node.id)
      if (key === 'output_length' && !GRAPH_MIX_OUTPUT_LENGTHS.some(option => option === value)) add('invalid_option', '混音输出时长仅支持 main 或 longest', node.id)
    }
    if (node.kind === 'export' && record(node.options) && !['srt', 'vtt', 'lrc'].includes(String(node.options.subtitle_format ?? 'srt'))) add('invalid_format', '字幕导出仅支持 SRT、VTT、LRC', node.id)
  }
  for (const slot of graph.input_slots) {
    if (!record(slot) || typeof slot.id !== 'string' || !identifier.test(slot.id) || [...slots.keys()].some(id => id.toLowerCase() === slot.id.toLowerCase())) { add('duplicate_or_invalid_slot', '素材槽编号无效或重复'); continue }
    slots.set(slot.id, slot)
    if (Object.keys(slot).some(key => !['id', 'type', 'label', 'language'].includes(key))) add('invalid_slot', '素材槽包含未知字段')
    if (!['audio', 'subtitle'].includes(slot.type) || typeof slot.label !== 'string' || !slot.label.trim() || slot.label.length > 100) add('invalid_slot', '请选择素材槽类型和名称')
    if (slot.language != null && !languages.has(slot.language)) add('invalid_language', '素材槽语言无效')
  }
  if (issues.length) return issues
  const connected = new Set<string>()
  for (const edge of graph.edges) {
    if (!record(edge) || !record(edge.source) || !record(edge.target)
        || Object.keys(edge).some(key => !['source', 'target'].includes(key))) { add('invalid_edge', '连线格式无效'); continue }
    const node = nodes.get(edge.target.node_id), port = edge.target.port
    if (!node || Object.keys(edge.target).some(key => !['node_id', 'port'].includes(key))) { add('unknown_target', '连线目标不存在'); continue }
    const expected = GRAPH_CATALOG[node.kind].inputs[port]
    if (!expected) { add('unknown_port', '节点没有该输入端口', node.id, port); continue }
    const target = `${node.id}:${port}`
    if (connected.has(target)) add('multiple_sources', '每个输入端口只能绑定一个来源', node.id, port)
    connected.add(target)
    let actual: GraphPortType | undefined
    if (edge.source.kind === 'slot' && Object.keys(edge.source).every(key => ['kind', 'slot_id'].includes(key))) actual = slots.get(edge.source.slot_id)?.type
    if (edge.source.kind === 'node' && Object.keys(edge.source).every(key => ['kind', 'node_id', 'port'].includes(key))) {
      const origin = nodes.get(edge.source.node_id)
      if (origin) actual = GRAPH_CATALOG[origin.kind].outputs[edge.source.port]
    }
    if (!actual) add('unknown_source', '连线来源节点、素材槽或端口不存在', node.id, port)
    else if (actual !== expected) add('type_mismatch', `该端口需要 ${expected}，来源为 ${actual}`, node.id, port)
  }
  for (const node of graph.nodes) for (const port of Object.keys(GRAPH_CATALOG[node.kind].inputs)) {
    if (!connected.has(`${node.id}:${port}`)) add('missing_input', '请选择素材槽或明确的上游产物', node.id, port)
  }
  const outputs = new Set<string>()
  for (const output of graph.outputs) {
    if (!record(output) || Object.keys(output).some(key => !['node_id', 'port', 'label'].includes(key))) { add('invalid_output', '产出格式无效'); continue }
    const node = nodes.get(output.node_id), key = `${output.node_id}:${output.port}`
    if (!node || !GRAPH_CATALOG[node.kind].outputs[output.port]) add('unknown_output', '交付产出的节点或端口不存在', output.node_id, output.port)
    if (outputs.has(key)) add('duplicate_output', '交付产出重复', output.node_id, output.port)
    outputs.add(key)
  }
  if (issues.length) return issues
  let order: string[]
  try { order = topologicalNodeIds(graph) } catch { return [{ code: 'cycle', message: '节点连线存在循环，请移除循环' }] }
  const resolved = new Map<string, GraphLanguage | null | undefined>()
  for (const id of order) {
    const node = nodes.get(id)!
    const input = graph.edges.find(edge => edge.target.node_id === id && edge.target.port === 'subtitle')?.source
    const language = input?.kind === 'slot' ? slots.get(input.slot_id)?.language : input?.kind === 'node' ? resolved.get(input.node_id) : undefined
    const expected = node.kind === 'tts' ? node.target_lang : node.source_lang
    if (['align', 'translate', 'tts'].includes(node.kind) && language && language !== expected) add('language_mismatch', `输入字幕语言 ${language} 与节点所需语言 ${expected} 不同`, id, 'subtitle')
    resolved.set(id, node.kind === 'asr' ? node.source_lang : node.kind === 'translate' ? node.target_lang : language)
  }
  return issues
}
