import type { CapabilityDescriptorResponse, CapabilityOptionResponse } from '@/api/types'
import type { Delivery, ReferenceAsset, SpeechConnection, SpeechProvider, SpeechRecipe, VoiceVariant } from '@/api/speech'
import { GRAPH_MIX_OUTPUT_LENGTHS } from './workflowGraph'
import type { GraphMixOutputLength, GraphNode } from './workflowGraph'
import { speechLanguageMatches, speechOptionsIssue } from './speechAdvancedOptions'

export interface GraphSpeechSource {
  mode: string
  variant: Pick<VoiceVariant, 'kind' | 'value'> & { style?: Delivery }
  connection_ref?: string
  provider_options: Record<string, unknown>
  default_delivery?: Delivery
  default_emotion?: string
  default_pause_ms?: number
}

export function readGraphSpeechSource(node: GraphNode): GraphSpeechSource | undefined {
  const value = node.options.speech_source
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const source = value as GraphSpeechSource
  if (typeof source.mode !== 'string' || !source.variant || typeof source.variant !== 'object'
      || typeof source.variant.value !== 'string' || typeof source.variant.kind !== 'string') return undefined
  if (source.provider_options !== undefined && (!source.provider_options || typeof source.provider_options !== 'object' || Array.isArray(source.provider_options))) return undefined
  return { ...source, provider_options: source.provider_options ?? { schema_version: 1 } }
}

/** Every edit returns a detached node; repeated TTS instances never share a draft. */
export function withGraphSpeechSource(node: GraphNode, source: GraphSpeechSource): GraphNode {
  return { ...node, options: { speech_source: structuredClone(source) }, provider_options: {} }
}

export function graphNodeFromRecipe(node: GraphNode, recipe: SpeechRecipe): GraphNode {
  return { ...node, provider: recipe.provider_id, model: recipe.model,
    options: { speech_recipe_id: recipe.id }, provider_options: {} }
}

export function copyRecipeToGraphNode(node: GraphNode, recipe: SpeechRecipe): GraphNode {
  if ('device' in recipe.provider_options) throw new Error('此旧预设包含设备设置，请先在声音页迁移到连接后另存；仍可直接引用原预设。')
  const source: GraphSpeechSource = {
    mode: recipe.mode, variant: { ...recipe.variant }, connection_ref: recipe.connection_ref,
    provider_options: structuredClone(recipe.provider_options),
    ...(recipe.default_delivery !== undefined ? { default_delivery: recipe.default_delivery } : {}),
    ...(recipe.default_emotion !== undefined ? { default_emotion: recipe.default_emotion } : {}),
    ...(recipe.default_pause_ms !== undefined ? { default_pause_ms: recipe.default_pause_ms } : {}),
  }
  return withGraphSpeechSource({ ...node, provider: recipe.provider_id, model: recipe.model }, source)
}

export function freshGraphSpeechNode(node: GraphNode, provider: SpeechProvider, model?: string, modeId?: string): GraphNode {
  const modes = provider.modes.filter(mode => !model || !mode.models.length || mode.models.includes(model))
  const mode = modes.find(item => item.id === modeId) ?? modes.find(item => item.voice_sources?.default != null) ?? modes[0]
  if (!mode) return { ...node, provider: provider.provider_id, model: model || null, options: {}, provider_options: {} }
  const source: GraphSpeechSource = { mode: mode.id,
    variant: { kind: mode.variant_kinds[0] ?? 'default', value: mode.voice_sources?.default ?? '' },
    provider_options: { schema_version: 1 } }
  const old = readGraphSpeechSource(node)
  // A connection belongs to an engine, not to a model. Never guess among connections.
  if (node.provider === provider.provider_id && old?.connection_ref) source.connection_ref = old.connection_ref
  return withGraphSpeechSource({ ...node, provider: provider.provider_id, model: model ?? mode.models[0] ?? null }, source)
}

export function graphSpeechIssue(node: GraphNode, provider: SpeechProvider | undefined,
  recipes: SpeechRecipe[], assets: ReferenceAsset[], connections: SpeechConnection[]): string {
  if (!provider) return '当前配音引擎不可用，请选择引擎或刷新能力。'
  const recipeId = node.options.speech_recipe_id
  const recipe = typeof recipeId === 'string' ? recipes.find(item => item.id === recipeId && !item.archived) : undefined
  if (recipeId && !recipe) return '引用的 TTS 高级预设不存在或已归档，请重新选择。'
  if (recipe && (recipe.provider_id !== node.provider || recipe.model !== node.model)) return '预设与此节点的引擎或模型不一致，请重新应用。'
  if (recipe && !speechLanguageMatches(recipe.language, node.target_lang ?? '')) return `预设合成目标语言 ${recipe.language} 与节点目标语言不一致，请选择匹配预设或自行调整语言。`
  const source = recipe ? { ...recipe, provider_options: recipe.provider_options } : readGraphSpeechSource(node)
  if (!source) return '请选择 TTS 高级预设或明确配置声音来源。'
  const mode = provider.modes.find(item => item.id === source.mode && (!item.models.length || item.models.includes(node.model ?? '')))
  if (!mode || !mode.variant_kinds.includes(source.variant.kind)) return '当前声音来源与引擎模型不兼容，请重新配置。'
  if (!node.model || node.model === 'default') return '请明确选择或填写配音模型。'
  const ref = source.connection_ref
  const implicit = !provider.connection_required && (!ref || ref === `engine-default-${node.provider}`)
  if (!implicit && !connections.some(item => item.id === ref && item.provider_id === node.provider)) return '请选择此引擎可用的连接；原连接不存在或不属于当前引擎。'
  if (mode.voice_sources?.required && !source.variant.value.trim()) return mode.voice_sources.description || '请补齐声音来源。'
  if (mode.voice_sources?.presets.length && !mode.voice_sources.allow_custom && !mode.voice_sources.presets.some(item => item.id === source.variant.value)) return '声音不在此引擎允许的预设列表中，请重新选择。'
  const capabilities = mode.capabilities ?? provider.capabilities
  const delivery = capabilities.delivery as Record<string, { support?: string }> | undefined
  if (source.default_delivery && source.default_delivery !== 'normal' && delivery?.[source.default_delivery]?.support !== 'direct' && source.variant.style !== source.default_delivery) return '当前模式不支持所选默认演绎，请选择自然或匹配风格的参考录音。'
  const emotion = capabilities.emotion as { support?: string } | undefined
  if (source.default_emotion && source.default_emotion !== 'neutral' && emotion?.support !== 'direct') return '当前模式不支持独立情绪控制，请选择自然。'
  if (source.default_pause_ms !== undefined && (!Number.isInteger(source.default_pause_ms) || source.default_pause_ms < 0 || source.default_pause_ms > 30000)) return '句后停顿须为 0–30000 毫秒整数。'
  if (source.variant.kind === 'reference') {
    const asset = assets.find(item => item.id === source.variant.value && !item.archived)
    if (!asset) return '请选择声音库中可用的参考录音。'
    const requirement = (mode.capabilities?.reference ?? provider.capabilities.reference) as { transcript_required?: boolean } | undefined
    const needsText = requirement?.transcript_required || provider.provider_id === 'qwen3'
    const optional = provider.provider_id === 'qwen3' && source.provider_options.x_vector_only_mode === true
    if (needsText && !optional && (!asset.transcript.trim() || asset.confirmed !== true)) return '当前参考克隆需要已核对的录音原文；Qwen 可显式启用“仅使用声音特征”。'
  }
  const values = recipe && 'device' in source.provider_options
    ? Object.fromEntries(Object.entries(source.provider_options).filter(([key]) => key !== 'device')) : source.provider_options
  return speechOptionsIssue(provider, source.mode, values, node.model ?? '')
}

const reservedOptions = new Set(['language', 'source_lang', 'target_lang', 'connection_ref'])
export type GraphParameterSection = 'common' | 'advanced' | 'all'

export const graphMixOutputLengthOptions: { value: GraphMixOutputLength; label: string; description: string }[] = [
  { value: 'main', label: '跟随主音轨（默认）', description: '输出时长跟随主音轨，超出主音轨结束位置的配音会被截断。' },
  { value: 'longest', label: '保留完整音轨', description: '输出时长取主音轨与偏移后配音结束位置的较长值，音轨空缺部分补静音。' },
]

/** Old templates inherit main; invalid saved values remain visible for correction. */
export function graphMixOutputLength(node: GraphNode): GraphMixOutputLength | null {
  return node.options.output_length === undefined ? 'main'
    : GRAPH_MIX_OUTPUT_LENGTHS.find(value => value === node.options.output_length) ?? null
}

export function graphNodeHasAdvancedParameters(node: GraphNode): boolean {
  return !['align', 'export'].includes(node.kind) && !(node.kind === 'tts' && node.options.speech_recipe_id)
}

export function editableGraphOptions(fields: CapabilityOptionResponse[]): CapabilityOptionResponse[] {
  return fields.filter(field => !field.secret && !reservedOptions.has(field.name)
    && !field.name.endsWith('_path') && !['api_key', 'credential', 'token', 'headers'].includes(field.name)
    && (['string', 'number', 'integer', 'boolean', 'object'].includes(field.type)
      || field.type === 'array' && field.name === 'hotwords'))
}

export function unknownGraphOptions(node: GraphNode, descriptor: CapabilityDescriptorResponse): string[] {
  return ([['options', descriptor.common_option_schema], ['provider_options', descriptor.provider_option_schema]] as const)
    .flatMap(([scope, fields]) => Object.keys(node[scope]).filter(key => !(scope === 'options' && key === 'connection_ref')
      && !fields.some(field => field.name === key)).map(key => `${scope}.${key}`))
}

/** A declared option can be preserved without being offered as a portable graph input. */
export function retainedGraphOptions(node: GraphNode, descriptor: CapabilityDescriptorResponse): string[] {
  return ([['options', descriptor.common_option_schema], ['provider_options', descriptor.provider_option_schema]] as const)
    .flatMap(([scope, fields]) => Object.keys(node[scope]).filter(key => fields.some(field => field.name === key)
      && !reservedOptions.has(key) && !editableGraphOptions(fields).some(field => field.name === key))
      .map(key => `${scope}.${key}`))
}

export function graphCapabilityValue(node: GraphNode, field: CapabilityOptionResponse, value: unknown): unknown {
  if (node.provider === 'qwen3_asr' && field.name === 'return_time_stamps'
      && node.provider_options.forced_aligner) return true
  return value ?? field.default
}

export function graphCapabilityDisabledReason(node: GraphNode, key: string): string {
  if (node.provider === 'qwen3_asr' && key === 'return_time_stamps' && node.provider_options.forced_aligner)
    return '已指定对齐模型，实际执行会启用时间戳；清空对齐模型后可关闭。原参数保留。'
  return ''
}

/** Validate only the declared JSON container; nested kwargs belong to the upstream engine. */
export function parseGraphObjectOption(text: string): { value?: Record<string, unknown>; error?: string } {
  try {
    const value: unknown = JSON.parse(text, (_key, item: unknown) => {
      if (typeof item === 'number' && !Number.isFinite(item)) throw new Error('non-finite JSON number')
      return item
    })
    if (!value || typeof value !== 'object' || Array.isArray(value)) return { error: '请输入 JSON 对象（不能是数组、null 或标量）。' }
    return { value: value as Record<string, unknown> }
  } catch { return { error: 'JSON 格式无效或数字超出有限范围，尚未修改已保存参数。' } }
}

export function graphSpeechOptionDisabledReason(node: GraphNode, source: GraphSpeechSource, key: string): string {
  if (node.provider === 'qwen3' && source.provider_options.do_sample === false && ['temperature', 'top_p', 'top_k'].includes(key))
    return '随机采样已关闭，此参数暂不参与主生成采样；数值保留。'
  if (node.provider === 'fish_audio' && key === 'tag_density') {
    if (node.model === 's1') return 'S1 不使用标签密度；数值保留。'
    if (!(source.default_delivery && source.default_delivery !== 'normal')
      && !(source.default_emotion && source.default_emotion !== 'neutral')
      && !String(source.provider_options.style_description ?? '').trim()) return '设置演绎、情绪或风格描述后生效；数值保留。'
  }
  return ''
}

export function setGraphOption(node: GraphNode, scope: 'options' | 'provider_options', key: string, value: unknown): GraphNode {
  const options = { ...node[scope] }
  if (value === undefined || value === '') delete options[key]
  else options[key] = value
  return { ...node, [scope]: options }
}
