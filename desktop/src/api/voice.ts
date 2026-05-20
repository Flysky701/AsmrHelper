import { api } from './client'
import type {
  VoiceProfileSummaryResponse,
  VoiceProfileResponse,
  VoiceDesignRequest,
  VoiceDesignResponse,
  VoiceCloneRequest,
  VoiceCloneResponse,
  SegmentAnalyzeRequest,
  SegmentAnalyzeResponse,
  VoicePreviewRequest,
  VoicePreviewResponse,
} from './types'

export const voiceApi = {
  listProfiles: () =>
    api.get<VoiceProfileSummaryResponse[]>('/voice/profiles'),

  getProfile: (profileId: string) =>
    api.get<VoiceProfileResponse>(`/voice/profiles/${profileId}`),

  deleteProfile: (profileId: string) =>
    api.delete<void>(`/voice/profiles/${profileId}`),

  design: (body: VoiceDesignRequest) =>
    api.post<VoiceDesignResponse>('/voice/design', body),

  clone: (body: VoiceCloneRequest) =>
    api.post<VoiceCloneResponse>('/voice/clone', body),

  analyzeSegments: (body: SegmentAnalyzeRequest) =>
    api.post<SegmentAnalyzeResponse>('/voice/analyze-segments', body),

  preview: (profileId: string, body: VoicePreviewRequest) =>
    api.post<VoicePreviewResponse>(`/voice/profiles/${profileId}/preview`, body),
}
