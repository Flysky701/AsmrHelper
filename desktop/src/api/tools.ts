import { api } from './client'
import type {
  SeparationRequest,
  SeparationResponse,
  ConvertRequest,
  ConvertResponse,
  SplitRequest,
  SplitResponse,
  SubtitleTranslationRequest,
  SubtitleTranslationResponse,
  VolumePreviewRequest,
  VolumePreviewResponse,
} from './types'

export const toolsApi = {
  separate: (body: SeparationRequest) =>
    api.post<SeparationResponse>('/tools/separate', body),

  convert: (body: ConvertRequest) =>
    api.post<ConvertResponse>('/tools/convert', body),

  split: (body: SplitRequest) =>
    api.post<SplitResponse>('/tools/split', body),

  translateSubtitle: (body: SubtitleTranslationRequest) =>
    api.post<SubtitleTranslationResponse>('/tools/translate-subtitle', body),

  volumePreview: (body: VolumePreviewRequest) =>
    api.post<VolumePreviewResponse>('/tools/volume-preview', body),
}
