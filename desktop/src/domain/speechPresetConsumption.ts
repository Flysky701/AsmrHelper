import type { SpeechOverrides, SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { GraphNode } from './workflowGraph'
import { availableSpeechOptions, speechOptionsIssue } from './speechAdvancedOptions'

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
export function runtimeSpeechOptions(provider: SpeechProvider | undefined, recipe: SpeechRecipe) {
  const names = provider?.modes.find(mode => mode.id === recipe.mode)?.runtime_options ?? []
  return availableSpeechOptions(provider, recipe.mode, recipe.model).filter(([key]) => names.includes(key)
    && !(provider?.provider_id === 'fish_audio' && recipe.model === 's1' && key === 'tag_density'))
}

export function speechOverrideIssue(provider: SpeechProvider | undefined, recipe: SpeechRecipe, value: unknown): string {
  if (value === undefined) return ''
  if (!record(value) || Object.keys(value).some(key => !['provider_options', 'default_delivery', 'default_emotion', 'default_pause_ms'].includes(key))) return '本次微调含未知字段，原数据已保留，请在音色库处理。'
  const options = value.provider_options === undefined ? {} : value.provider_options
  if (!record(options) || Object.keys(options).some(key => !runtimeSpeechOptions(provider, recipe).some(([name]) => name === key))) return '存在当前音色不支持的微调，原数据已保留。'
  const caps = provider?.modes.find(mode => mode.id === recipe.mode)?.capabilities ?? provider?.capabilities
  const delivery = caps?.delivery as Record<string, { support?: string }> | undefined
  const emotion = caps?.emotion as { support?: string } | undefined
  const pause = caps?.pause as { support?: string } | undefined
  if (value.default_delivery !== undefined && (typeof value.default_delivery !== 'string' || delivery?.[value.default_delivery]?.support !== 'direct')) return '当前音色不支持此演绎微调。'
  if (value.default_emotion !== undefined && (emotion?.support !== 'direct' || !['neutral', 'happy', 'sad', 'angry', 'excited', 'calm', 'nervous', 'relaxed'].includes(String(value.default_emotion)))) return '当前音色不支持此情绪微调。'
  if (value.default_pause_ms !== undefined && (pause?.support !== 'postprocess' || typeof value.default_pause_ms !== 'number' || !Number.isInteger(value.default_pause_ms) || value.default_pause_ms < 0 || value.default_pause_ms > 30000)) return '句后停顿须为 0–30000 毫秒整数。'
  return speechOptionsIssue(provider, recipe.mode, options, recipe.model)
}

export function effectiveSpeechRecipe(recipe: SpeechRecipe, overrides: SpeechOverrides = {}): SpeechRecipe {
  return { ...structuredClone(recipe), ...structuredClone(overrides), provider_options: { ...recipe.provider_options, ...overrides.provider_options } }
}

export function withSpeechOverrides(node: GraphNode, overrides: SpeechOverrides): GraphNode {
  const options = { ...node.options }
  const patch = structuredClone(overrides)
  for (const key of Object.keys(patch) as (keyof SpeechOverrides)[]) if (patch[key] === undefined) delete patch[key]
  if (patch.provider_options && !Object.keys(patch.provider_options).length) delete patch.provider_options
  if (Object.keys(patch).length) options.speech_overrides = patch
  else delete options.speech_overrides
  return { ...node, options }
}
