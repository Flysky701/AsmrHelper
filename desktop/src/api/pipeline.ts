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
  createGraphPreset: (body: GraphPresetDraft) => api.post<GraphPresetItem>('/pipeline/presets', body),
  updateGraphPreset: (id: string, body: GraphPresetDraft & { revision: number }) =>
    api.put<GraphPresetItem>(`/pipeline/presets/${encodeURIComponent(id)}`, body),
  createPreset: (body: FlowPresetDraft) => api.post<PresetItem>('/pipeline/presets', body),
  updatePreset: (id: string, body: FlowPresetDraft & { revision: number }) => api.put<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}`, body),
  copyPreset: (id: string, label: string) => api.post<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}/copy`, { label }),
}
