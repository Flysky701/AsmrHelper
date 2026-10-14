import { create } from 'zustand'
import type { PageHelpTopic } from '@/domain/pageHelp'

interface PageHelpState {
  openTopic: PageHelpTopic | null
  toggle: (topic: PageHelpTopic) => void
  dismiss: (topic?: PageHelpTopic) => void
}

// Deliberately transient: help never reopens from saved preferences or drafts.
export const usePageHelpStore = create<PageHelpState>((set) => ({
  openTopic: null,
  toggle: topic => set(state => ({ openTopic: state.openTopic === topic ? null : topic })),
  dismiss: topic => set(state => topic && state.openTopic !== topic ? state : { openTopic: null }),
}))
