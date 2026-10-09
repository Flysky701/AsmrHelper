import { create } from 'zustand'
import type { SpeechRecipe } from '@/api/speech'
import type { GraphNode } from '@/domain/workflowGraph'
import type { PageId } from './navStore'

// Route changes retain the editor without persisting credentials or a new library.
export interface VoiceLabDraft {
  recipe: SpeechRecipe
  dirty: boolean
  referenceId: string
  script: string
  returnTo: PageId | null
  retainedNode: GraphNode | null
  migrationIssues: string[]
}
export const useVoiceLabDraftStore = create<{ draft: VoiceLabDraft | null }>(() => ({ draft: null }))
