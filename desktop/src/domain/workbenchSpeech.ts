import type { SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { SpeechEngineDraft } from '@/stores/speechDraftStore'

export function compatibleSpeechRules(provider: SpeechProvider | undefined, model: string, recipes: SpeechRecipe[]) {
  if (!provider || !model) return []
  return recipes.filter(recipe => !recipe.archived && recipe.provider_id === provider.provider_id
    && recipe.model === model && provider.modes.some(mode => mode.id === recipe.mode
      && mode.variant_kinds.includes(recipe.variant.kind)
      && (!mode.models.length || mode.models.includes(model))))
}

export function initialSpeechEngine(provider: SpeechProvider, model?: string): SpeechEngineDraft {
  const modes = provider.modes.filter(mode => !model || !mode.models.length || mode.models.includes(model))
  const mode = modes.find(mode => mode.voice_sources?.default != null) ?? modes[0]
  return {
    providerId: provider.provider_id, model: model ?? mode?.models[0] ?? '',
    mode: mode?.id ?? '', value: mode?.voice_sources?.default ?? '', connectionRef: '',
    providerOptions: { schema_version: 1 },
  }
}
