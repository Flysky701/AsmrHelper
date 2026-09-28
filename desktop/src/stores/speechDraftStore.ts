import { create } from 'zustand'
import type { SpeechRecipe } from '@/api/speech'

export interface SpeechEngineDraft {
  providerId: string
  model: string
  mode: string
  value: string
  connectionRef: string
  providerOptions: Record<string, unknown>
}

interface SpeechDraftState {
  recipeId: string | null
  recipe: SpeechRecipe | null
  engine: SpeechEngineDraft | null
  setEngine: (engine: SpeechEngineDraft) => void
  setRecipe: (recipe: SpeechRecipe) => void
  clear: () => void
}

export const useSpeechDraftStore = create<SpeechDraftState>((set) => ({
  recipeId: null,
  recipe: null,
  engine: null,
  setEngine: (engine) => set({ engine: structuredClone(engine), recipeId: null, recipe: null }),
  setRecipe: (recipe) => set({ recipeId: recipe.id, recipe: structuredClone(recipe), engine: {
    providerId: recipe.provider_id, model: recipe.model, mode: recipe.mode,
    value: recipe.variant.value, connectionRef: recipe.connection_ref,
    providerOptions: structuredClone(recipe.provider_options),
  } }),
  clear: () => set({ recipeId: null, recipe: null }),
}))
