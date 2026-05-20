import { api } from './client'
import type {
  PipelineRunRequest,
  PipelineRunResponse,
  PipelinePresetsResponse,
  BatchPipelineRequest,
  BatchPipelineResponse,
} from './types'

export const pipelineApi = {
  run: (body: PipelineRunRequest) =>
    api.post<PipelineRunResponse>('/pipeline/run', body),

  presets: () => api.get<PipelinePresetsResponse>('/pipeline/presets'),

  batch: (body: BatchPipelineRequest) =>
    api.post<BatchPipelineResponse>('/pipeline/batch', body),
}
