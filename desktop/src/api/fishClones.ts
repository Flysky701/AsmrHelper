import { api } from './client'
import type { SpeechRecipe } from './speech'

export interface FishCloneDraft { connection_ref: string; asset_id: string; title: string }
export interface FishClonePreview extends FishCloneDraft {
  token: string; endpoint: string; asset_name: string; bytes: number; duration?: number; transcript: string; visibility: string
}
export interface FishClone {
  id: string; title: string; asset_id: string; connection_ref: string; state: string
  remote_voice_id: string | null; message: string; recipe_id: string | null
  deleted?: boolean
  updated_at?: string
}
export const fishClonesApi = {
  list: () => api.get<{ items: FishClone[] }>('/speech/fish-clones?include_deleted=true'),
  preview: (draft: FishCloneDraft) => api.post<FishClonePreview>('/speech/fish-clones/preview', draft),
  create: (draft: FishCloneDraft, token: string, requestId: string) => api.post<FishClone>('/speech/fish-clones', {
    ...draft, token, request_id: requestId,
  }),
  refresh: (id: string) => api.post<FishClone>(`/speech/fish-clones/${encodeURIComponent(id)}/refresh`),
  save: (id: string) => api.post<SpeechRecipe>(`/speech/fish-clones/${encodeURIComponent(id)}/rule`),
  remove: (id: string) => api.delete<FishClone>(`/speech/fish-clones/${encodeURIComponent(id)}`),
  restore: (id: string) => api.post<FishClone>(`/speech/fish-clones/${encodeURIComponent(id)}/restore`),
}
