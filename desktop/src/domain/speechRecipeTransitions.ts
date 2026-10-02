import type { ReferenceAsset, SpeechMode, SpeechProvider, SpeechRecipe, VoiceVariant } from '@/api/speech'
import { availableSpeechOptions, speechOptionsIssue } from './speechAdvancedOptions'

export function blankSpeechRecipe(): SpeechRecipe {
  return { id: '', revision: 0, name: '', voice_id: '', provider_id: '', model: '', mode: '', connection_ref: '',
    variant: { kind: 'reference', value: '', style: 'normal' }, language: 'auto', provider_options: { schema_version: 1 } }
}

export function referenceModes(provider: SpeechProvider | undefined): SpeechMode[] {
  return provider?.modes.filter(mode => mode.variant_kinds.includes('reference')) || []
}

function optionsFor(recipe: SpeechRecipe, provider: SpeechProvider | undefined, mode: string, model: string) {
  const options: Record<string, unknown> = { schema_version: 1 }
  if (!mode) return options
  for (const [key, field] of availableSpeechOptions(provider, mode, model)) {
    const value = recipe.provider_options[key]
    if (value !== undefined && !speechOptionsIssue(provider, mode, { schema_version: 1, [key]: value }, model)) options[key] = value
    else if (field.default !== undefined) options[key] = field.default
  }
  return options
}

function applySelection(recipe: SpeechRecipe, provider: SpeechProvider | undefined, mode: SpeechMode | undefined, model: string, variant: VoiceVariant): SpeechRecipe {
  const capabilities = mode?.capabilities || provider?.capabilities || {}
  const delivery = (capabilities.delivery || {}) as Record<string, { support?: string }>
  const emotion = capabilities.emotion as { support?: string } | undefined
  const pause = capabilities.pause as { support?: string } | undefined
  const defaultDelivery = recipe.default_delivery || 'normal'
  return { ...recipe, provider_id: provider?.provider_id || '', mode: mode?.id || '', model,
    connection_ref: recipe.provider_id === provider?.provider_id ? recipe.connection_ref : '',
    variant: { ...variant }, provider_options: optionsFor(recipe, provider, mode?.id || '', model),
    default_delivery: defaultDelivery === 'normal' || delivery[defaultDelivery]?.support === 'direct' ? defaultDelivery : 'normal',
    default_emotion: emotion?.support === 'direct' ? recipe.default_emotion || 'neutral' : 'neutral',
    default_pause_ms: pause?.support === 'postprocess' ? recipe.default_pause_ms || 0 : 0 }
}

function modelFor(mode: SpeechMode | undefined, previous = '') {
  if (!mode) return ''
  return !mode.models.length || mode.models.includes(previous) ? previous : mode.models[0] || ''
}

export function selectSpeechProvider(recipe: SpeechRecipe, provider: SpeechProvider | undefined): SpeechRecipe {
  const reference = recipe.variant.kind === 'reference' && !!recipe.variant.value
  const modes = reference ? referenceModes(provider) : provider?.modes || []
  const mode = modes.find(item => recipe.provider_id === provider?.provider_id && item.id === recipe.mode)
    || modes.find(item => item.variant_kinds.includes(recipe.variant.kind)) || modes[0]
  // A carried recording stays a recording even when the chosen provider cannot use it.
  // The empty mode/model and capability error require an explicit compatible choice.
  const variant = reference || (recipe.provider_id === provider?.provider_id && mode?.variant_kinds.includes(recipe.variant.kind))
    ? recipe.variant : { kind: mode?.variant_kinds[0] || recipe.variant.kind, value: mode?.voice_sources?.default || '', style: 'normal' as const }
  return applySelection(recipe, provider, mode, modelFor(mode, recipe.provider_id === provider?.provider_id ? recipe.model : ''), variant)
}

export function selectSpeechMode(recipe: SpeechRecipe, provider: SpeechProvider | undefined, id: string, retainedReferenceId = ''): SpeechRecipe {
  const mode = provider?.modes.find(item => item.id === id)
  if (!mode || !mode.variant_kinds[0]) return recipe
  const variant = mode.variant_kinds.includes(recipe.variant.kind) ? recipe.variant
    : mode.variant_kinds.includes('reference') && retainedReferenceId ? { kind: 'reference' as const, value: retainedReferenceId, style: 'normal' as const }
      : { kind: mode.variant_kinds[0], value: mode.voice_sources?.default || '', style: 'normal' as const }
  return applySelection(recipe, provider, mode, modelFor(mode, recipe.model), variant)
}

export function selectSpeechModel(recipe: SpeechRecipe, provider: SpeechProvider | undefined, model: string): SpeechRecipe {
  const mode = provider?.modes.find(item => item.id === recipe.mode)
  return applySelection(recipe, provider, mode, model, recipe.variant)
}

export function recipeFromReference(current: SpeechRecipe, asset: ReferenceAsset, providers: SpeechProvider[]): SpeechRecipe {
  const compatible = providers.filter(provider => referenceModes(provider).length)
  const provider = compatible.find(item => item.provider_id === current.provider_id) || (compatible.length === 1 ? compatible[0] : undefined)
  const mode = referenceModes(provider).find(item => item.id === current.mode) || referenceModes(provider)[0]
  const model = modelFor(mode, provider?.provider_id === current.provider_id ? current.model : '')
  const draft = { ...blankSpeechRecipe(), name: asset.name || '参考音色',
    provider_id: provider?.provider_id || '', connection_ref: provider?.provider_id === current.provider_id ? current.connection_ref : '' }
  return applySelection(draft, provider, mode, model, { kind: 'reference', value: asset.id, style: 'normal' })
}

export function speechRecipeCapabilityIssue(recipe: SpeechRecipe, provider: SpeechProvider | undefined): string {
  if (!provider) return recipe.variant.kind === 'reference' && recipe.variant.value ? '参考录音已保留，请选择支持参考声音克隆的引擎。' : '请选择引擎。'
  if (recipe.variant.kind === 'reference' && recipe.variant.value && !referenceModes(provider).length) return '当前引擎不支持用参考录音克隆声音。录音和原文已保留，请选择兼容引擎。'
  const mode = provider.modes.find(item => item.id === recipe.mode)
  if (!mode) return '请选择该引擎支持的生成方式。'
  if (!mode.variant_kinds.includes(recipe.variant.kind)) return '当前声音来源与生成方式不兼容，请重新选择生成方式。'
  if (!recipe.model.trim()) return '请选择模型。'
  if (mode.models.length && !mode.models.includes(recipe.model)) return '当前模型不支持所选生成方式，请选择列表中的兼容模型。'
  return ''
}
