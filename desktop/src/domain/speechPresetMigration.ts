import type { SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { GraphNode } from './workflowGraph'
import { blankSpeechRecipe } from './speechRecipeTransitions'
import { readGraphSpeechSource } from './graphNodeParameters'
import { effectiveSpeechRecipe, speechOverrideIssue } from './speechPresetConsumption'

/** No writes and no guessed cloud connection. The caller retains the raw node. */
export function speechRecipeFromNode(node: GraphNode, providers: SpeechProvider[], recipes: SpeechRecipe[]) {
  const issues: string[] = []
  const provider = providers.find(item => item.provider_id === node.provider)
  const saved = recipes.find(item => item.id === node.options.speech_recipe_id)
  const source = readGraphSpeechSource(node)
  let recipe = blankSpeechRecipe()
  if (saved) {
    if (node.options.speech_source !== undefined || node.options.voice !== undefined || node.options.speed !== undefined) issues.push('旧节点同时含已保存音色与直接来源参数。')
    const issue = speechOverrideIssue(provider, saved, node.options.speech_overrides)
    if (issue) issues.push(issue)
    recipe = issue ? structuredClone(saved) : effectiveSpeechRecipe(saved, node.options.speech_overrides ?? {})
  } else if (source) {
    recipe = { ...recipe, ...structuredClone(source), provider_id: node.provider, model: node.model ?? '',
      connection_ref: source.connection_ref ?? '', variant: { ...source.variant, style: source.variant.style ?? 'normal' },
      language: node.target_lang || String(node.options.language ?? 'auto') }
    const raw = node.options.speech_source as Record<string, unknown>
    if (Object.keys(raw).some(key => !['mode', 'variant', 'connection_ref', 'provider_options', 'default_delivery', 'default_emotion', 'default_pause_ms'].includes(key))
      || Object.keys(raw.variant as object).some(key => !['kind', 'value', 'style'].includes(key))) issues.push('声音来源含未识别字段。')
    if (node.options.speed !== undefined) {
      if (recipe.provider_options.speed !== undefined && recipe.provider_options.speed !== node.options.speed) issues.push('旧语速参数互相冲突。')
      else recipe.provider_options.speed = node.options.speed
    }
    if (node.options.voice !== undefined && node.options.voice !== recipe.variant.value) issues.push('旧声音标识互相冲突。')
  } else {
    const modes = provider?.modes.filter(mode => !mode.models.length || mode.models.includes(node.model ?? '')) ?? []
    const mode = modes.find(item => item.voice_sources?.default != null) ?? (modes.length === 1 ? modes[0] : undefined)
    recipe = { ...recipe, provider_id: node.provider, model: node.model ?? '', mode: mode?.id ?? '',
      language: node.target_lang || String(node.options.language ?? 'auto'),
      variant: { kind: mode?.variant_kinds[0] ?? 'default', value: typeof node.options.voice === 'string' ? node.options.voice : mode?.voice_sources?.default ?? '', style: 'normal' },
      provider_options: { schema_version: 1, ...(node.options.speed !== undefined ? { speed: node.options.speed } : {}) } }
    if (node.options.speech_source !== undefined || node.options.speech_recipe_id !== undefined) issues.push('旧声音来源或音色引用无法解析。')
  }
  if (!provider) issues.push('原引擎不可用。')
  if (node.options.speech_overrides !== undefined && !saved) issues.push('未找到本次微调对应的已保存音色。')
  if (Object.keys(node.options).some(key => !['speech_recipe_id', 'speech_overrides', 'speech_source', 'voice', 'speed', 'language'].includes(key)) || Object.keys(node.provider_options).length) issues.push('旧节点含未识别参数。')
  if (saved && (saved.provider_id !== node.provider || saved.model !== node.model)) issues.push('旧节点与音色引擎或模型不一致。')
  if (!recipe.connection_ref && provider && !provider.connection_required) recipe.connection_ref = `engine-default-${provider.provider_id}`
  return { recipe: { ...recipe, id: '', voice_id: '', revision: 0, archived: false, name: recipe.name ? `${recipe.name}（副本）` : '旧节点音色' }, issues }
}
