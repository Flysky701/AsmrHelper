import { create } from 'zustand'
import type { SpeechRecipe } from '@/api/speech'

interface SpeechDraftState {
  recipeId: string | null
  recipe: SpeechRecipe | null
  setRecipe: (recipe: SpeechRecipe) => void
  clear: () => void
}

export const useSpeechDraftStore = create<SpeechDraftState>((set) => ({
  recipeId: null,
  recipe: null,
  setRecipe: (recipe) => set({ recipeId: recipe.id, recipe: structuredClone(recipe) }),
  clear: () => set({ recipeId: null, recipe: null }),
}))
