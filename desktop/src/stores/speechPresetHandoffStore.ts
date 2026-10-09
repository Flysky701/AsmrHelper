import { create } from 'zustand'
import type { GraphNode } from '@/domain/workflowGraph'
import { useNavStore } from './navStore'
import type { PageId } from './navStore'

/** One explicit handoff; the original workflow stays in its existing draft store. */
export interface SpeechPresetHandoff {
  token: string
  returnTo: PageId
  recipeId?: string
  nodeDraft?: GraphNode
}

interface HandoffState {
  pending: SpeechPresetHandoff | null
  navigating: boolean
  acknowledge: (token: string) => void
}

export const useSpeechPresetHandoffStore = create<HandoffState>((set, get) => ({
  pending: null,
  navigating: false,
  acknowledge: token => { if (get().pending?.token === token) set({ pending: null }) },
}))

export async function openSpeechPresetLibrary(input: { recipeId?: string; nodeDraft?: GraphNode } = {}) {
  const store = useSpeechPresetHandoffStore
  if (store.getState().navigating) return false
  if (store.getState().pending) {
    store.setState({ navigating: true })
    try {
      await useNavStore.getState().setPage('voice-lab')
      return useNavStore.getState().activePage === 'voice-lab'
    } finally { store.setState({ navigating: false }) }
  }
  const returnTo = useNavStore.getState().activePage
  store.setState({ navigating: true })
  try {
    await useNavStore.getState().setPage('voice-lab')
    if (useNavStore.getState().activePage !== 'voice-lab') return false
    store.setState({ pending: { ...structuredClone(input), token: crypto.randomUUID(), returnTo } })
    return true
  } finally { store.setState({ navigating: false }) }
}
