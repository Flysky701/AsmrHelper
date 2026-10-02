import { api } from './client'
import type {
  PipelineRunRequest,
  PipelineTaskCreateResponse,
  PipelinePresetsResponse,
  PresetItem,
  FlowPresetDraft,
  GraphPipelineRunRequest,
  GraphPresetDraft,
  GraphPresetItem,
} from './types'

export const pipelineApi = {
  createTask: (body: PipelineRunRequest | GraphPipelineRunRequest) =>
    api.post<PipelineTaskCreateResponse>('/pipeline-runs', body),

  presets: () => api.get<PipelinePresetsResponse>('/pipeline/presets'),
  graphPresets: () => api.get<{ presets: (PresetItem | GraphPresetItem)[] }>('/pipeline/presets?include_graph=true'),
  archivedPresets: () => api.get<{ presets: (PresetItem | GraphPresetItem)[] }>('/pipeline/presets/archived?include_graph=true'),
  restorePreset: (id: string, revision: number, label?: string) =>
    api.post<PresetItem | GraphPresetItem>(`/pipeline/presets/${encodeURIComponent(id)}/restore`, { revision, ...(label === undefined ? {} : { label }) }),
  graphDraft: (id: string) => api.get<{
    source: PresetItem | GraphPresetItem
    graph: import('../domain/workflowGraph').GraphDefinition
    warnings: string[]
  }>(`/pipeline/presets/${encodeURIComponent(id)}/graph-draft`),
  createGraphPreset: (body: GraphPresetDraft) => api.post<GraphPresetItem>('/pipeline/presets', body),
  updateGraphPreset: (id: string, body: GraphPresetDraft & { revision: number }) =>
    api.put<GraphPresetItem>(`/pipeline/presets/${encodeURIComponent(id)}`, body),
  deletePreset: (id: string, revision: number) =>
    api.delete<void>(`/pipeline/presets/${encodeURIComponent(id)}?revision=${revision}`),
  createPreset: (body: FlowPresetDraft) => api.post<PresetItem>('/pipeline/presets', body),
  updatePreset: (id: string, body: FlowPresetDraft & { revision: number }) => api.put<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}`, body),
  copyPreset: (id: string, label: string) => api.post<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}/copy`, { label }),
}
