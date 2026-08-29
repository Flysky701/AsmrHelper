import { api } from './client'
import type {
  VoiceProfileSummaryResponse,
  VoiceProfileResponse,
  VoiceDesignRequest,
  VoiceCloneRequest,
  SegmentAnalyzeRequest,
  SegmentAnalyzeResponse,
  SegmentInfo,
  VoiceCloneCandidate,
  VoicePreviewRequest,
  TaskStatusResponse,
} from './types'

function legacyCandidateId(segment: SegmentInfo, position: number): string {
  return `legacy-${Number.isFinite(segment.index) ? segment.index : position}`
}

export function normalizeSegmentAnalyzeResponse(response: SegmentAnalyzeResponse): SegmentAnalyzeResponse {
  if (response.candidates) {
    const missingEligibility = response.candidates.some((candidate) => candidate.eligible !== true && candidate.eligible !== false)
    return {
      ...response,
      candidates: response.candidates.map((candidate) => ({
        ...candidate,
        details: candidate.details ?? {},
        eligible: candidate.eligible === true,
        reasons: candidate.reasons ?? [],
        preview_audio_path: candidate.preview_audio_path ?? '',
      })),
      recommended_candidate_id: response.recommended_candidate_id ?? null,
      warnings: [
        ...(response.warnings ?? []),
        ...(missingEligibility ? ['后端未返回候选合格状态；为避免使用被质量规则淘汰的片段，已禁止克隆，请升级后重新分析。'] : []),
      ],
    }
  }

  // A transitional backend may expose an analysis id without the candidate
  // contract. Do not invent candidate ids that the backend cannot resolve.
  if (response.analysis_id) {
    return {
      ...response,
      candidates: [],
      recommended_candidate_id: null,
      warnings: [
        ...(response.warnings ?? []),
        '后端分析结果缺少可绑定的候选标识，请升级后重新分析。',
      ],
    }
  }

  const segments = response.segments ?? []
  const candidates: VoiceCloneCandidate[] = segments.map((segment, position) => ({
    candidate_id: legacyCandidateId(segment, position),
    source_variant: 'original',
    start: segment.start,
    end: segment.end,
    text: segment.text,
    score: segment.score,
    label: segment.label,
    details: segment.details ?? {},
    eligible: false,
    reasons: [],
    preview_audio_path: '',
  }))
  const recommendedIndex = response.recommended_indices?.[0]
  const recommendedPosition = recommendedIndex === undefined
    ? -1
    : segments.findIndex((segment, position) => segment.index === recommendedIndex || position === recommendedIndex)

  return {
    ...response,
    candidates,
    recommended_candidate_id: recommendedPosition >= 0
      ? candidates[recommendedPosition]?.candidate_id ?? null
      : null,
    warnings: response.warnings ?? [],
  }
}

export const voiceApi = {
  listProfiles: () =>
    api.get<VoiceProfileSummaryResponse[]>('/voice/profiles'),

  getProfile: (profileId: string) =>
    api.get<VoiceProfileResponse>(`/voice/profiles/${profileId}`),

  deleteProfile: (profileId: string) =>
    api.delete<void>(`/voice/profiles/${profileId}`),

  design: (body: VoiceDesignRequest) =>
    api.post<TaskStatusResponse>('/voice/design', body),

  clone: (body: VoiceCloneRequest) =>
    api.post<TaskStatusResponse>('/voice/clone', body),

  analyzeSegments: async (body: SegmentAnalyzeRequest) =>
    normalizeSegmentAnalyzeResponse(await api.post<SegmentAnalyzeResponse>('/voice/analyze-segments', body)),

  preview: (profileId: string, body: VoicePreviewRequest) =>
    api.post<TaskStatusResponse>(`/voice/profiles/${profileId}/preview`, body),
}
