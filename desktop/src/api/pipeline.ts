import { api } from './client'
import type {
  PipelineRunRequest,
  PipelineTaskCreateResponse,
  PipelinePresetsResponse,
  PresetItem,
  FlowPresetDraft,
} from './types'

export const pipelineApi = {
  createTask: (body: PipelineRunRequest) =>
    api.post<PipelineTaskCreateResponse>('/pipeline-runs', body),

  presets: () => api.get<PipelinePresetsResponse>('/pipeline/presets'),
  createPreset: (body: FlowPresetDraft) => api.post<PresetItem>('/pipeline/presets', body),
  updatePreset: (id: string, body: FlowPresetDraft & { revision: number }) => api.put<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}`, body),
  copyPreset: (id: string, label: string) => api.post<PresetItem>(`/pipeline/presets/${encodeURIComponent(id)}/copy`, { label }),
}
