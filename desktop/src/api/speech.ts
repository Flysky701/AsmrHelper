import { api, apiUrl } from './client'
import type { TaskStatusResponse } from './types'

export type Delivery = 'normal' | 'soft' | 'whisper'
export type VariantKind = 'hosted' | 'builtin' | 'reference' | 'design'
export interface VoiceVariant { kind: VariantKind; value: string; style: Delivery }
export interface SpeechVoice { id: string; name: string; description: string; bindings: { provider_id: string; variants: VoiceVariant[] }[]; default_binding: string }
export interface SpeechRecipe { id: string; revision: number; name: string; voice_id: string; provider_id: string; model: string; mode: string; connection_ref: string; variant: VoiceVariant; language: string; provider_options: Record<string, unknown>; default_delivery?: Delivery; default_emotion?: string; default_pause_ms?: number }
export interface SpeechSegment { id: string; start: number; end: number; delivery: Delivery; emotion: string; pause_ms: number }
export interface SpeechPlan { id: string; text: string; text_hash: string; segments: SpeechSegment[] }
export interface ReferenceAsset { id: string; path: string; source_path?: string; transcript: string; language: string; start?: number; end?: number; duration?: number; confirmed?: boolean }
export interface SpeechConnection { id: string; name: string; provider_id: string; deployment: 'local' | 'lan' | 'cloud'; base_url?: string; credential_configured?: boolean; timeout?: number; model_path?: string; device?: string }
export interface SpeechTake { id: string; task_id: string; experiment_id: string; plan_id: string; segment_id: string; recipe_id: string; compiled_request: Record<string, unknown>; audio: { duration?: number; sample_rate?: number; channels?: number }; elapsed_seconds: number; status: string }
export interface SpeechExperiment { id: string; name: string; plan_id: string; takes?: SpeechTake[]; kind?: string; task_id?: string }
export interface TakeSelection { experiment_id: string; segment_id: string; take_id: string }
export interface SpeechAssembly { id: string; experiment_id: string; revision?: number; audio?: Record<string, unknown>; status?: string }
export interface OptionSchema { type?: string; title?: string; description?: string; enum?: (string | number)[]; default?: unknown; minimum?: number; maximum?: number; const?: unknown }
export interface SpeechProvider { provider_id: string; name: string; remote: boolean; version: string; connection_required: boolean; modes: { id: string; variant_kinds: VariantKind[]; models: string[]; capabilities?: Record<string, unknown> }[]; options_schema: { properties: Record<string, OptionSchema> }; capabilities: Record<string, unknown> }
export interface SpeechLibrary { voices: SpeechVoice[]; recipes: SpeechRecipe[]; assets: ReferenceAsset[]; experiments: SpeechExperiment[]; takes: SpeechTake[]; plans: SpeechPlan[]; selections: TakeSelection[]; assemblies: SpeechAssembly[]; connections: SpeechConnection[] }
export interface Waveform { id?: string; duration: number; peaks: number[] }

export const speechApi = {
  providers: () => api.get<{ providers: SpeechProvider[] }>('/speech/providers'),
  library: () => api.get<SpeechLibrary>('/speech/library'),
  voice: ({ id, ...voice }: Omit<SpeechVoice, 'id'> & { id?: string }) => api.post<SpeechVoice>('/speech/voices', { ...voice, ...(id ? { id } : {}) }),
  recipe: (recipe: Partial<SpeechRecipe>) => api.post<SpeechRecipe>('/speech/recipes', recipe),
  plan: (plan: { text: string; segments?: SpeechSegment[] }) => api.post<SpeechPlan>('/speech/plans', plan),
  planPerformance: (plan_id: string, connection_ref?: string) => api.post<SpeechPlan>('/speech/plan-performance', { plan_id, ...(connection_ref ? { connection_ref } : {}) }),
  connection: (connection: Partial<SpeechConnection> & { api_key?: string }) => api.post<SpeechConnection>('/speech/connections', connection),
  probe: (id: string, model: string, mode: string) => api.post<Record<string, unknown>>(`/speech/connections/${encodeURIComponent(id)}/probe`, { model, mode }),
  inspect: (path: string) => api.post<Waveform & { id: string; path: string }>('/speech/references/inspect', { path }),
  analyze: (path: string, language: string, separate_vocals: boolean) => api.post<{ original: Waveform & { id: string; path: string }; analyzed: Waveform & { id: string; path: string }; segments: { start: number; end: number; text: string }[] }>('/speech/references/analyze', { path, language, separate_vocals }),
  reference: (reference: { path: string; start: number; end: number; transcript: string; language: string; confirmed: true }) => api.post<ReferenceAsset>('/speech/references', reference),
  waveform: (id: string) => api.get<Waveform>(`/speech/references/${encodeURIComponent(id)}/waveform`),
  referenceAudio: (id: string, source = false) => apiUrl(`/speech/references/${encodeURIComponent(id)}/audio?source=${source}`),
  compile: (recipe_id: string, plan_id: string) => api.post<{ requests: Record<string, unknown>[] }>('/speech/compile', { recipe_id, plan_id }),
  experiment: (name: string, plan_id: string) => api.post<SpeechExperiment>('/speech/experiments', { name, plan_id }),
  getExperiment: (id: string) => api.get<SpeechExperiment>(`/speech/experiments/${encodeURIComponent(id)}`),
  generate: (id: string, recipe_id: string, plan_id: string, segment_id?: string) => api.post<TaskStatusResponse>(`/speech/experiments/${encodeURIComponent(id)}/generate`, { recipe_id, plan_id, ...(segment_id ? { segment_id } : {}) }),
  select: (selection: TakeSelection) => api.post<TakeSelection>('/speech/selections', selection),
  takeAudio: (id: string) => apiUrl(`/speech/takes/${encodeURIComponent(id)}/audio`),
  assembly: (experiment_id: string) => api.post<SpeechAssembly>('/speech/assemblies', { experiment_id }),
  assemblyAudio: (id: string) => apiUrl(`/speech/assemblies/${encodeURIComponent(id)}/audio`),
  workbenchDraft: (recipe_id: string) => api.post<{ recipe: SpeechRecipe }>('/speech/workbench-draft', { recipe_id }),
}
