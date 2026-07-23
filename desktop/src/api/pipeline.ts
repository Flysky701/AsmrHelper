import { api } from './client'
import type {
  PipelineRunRequest,
  PipelineTaskCreateResponse,
  PipelinePresetsResponse,
  BatchPipelineRequest,
  BatchPipelineResponse,
} from './types'

export const pipelineApi = {
  createTask: (body: PipelineRunRequest) =>
    api.post<PipelineTaskCreateResponse>('/pipeline-runs', body),

  presets: () => api.get<PipelinePresetsResponse>('/pipeline/presets'),

  batch: (body: BatchPipelineRequest) =>
    api.post<BatchPipelineResponse>('/pipeline/batch', body),
}
