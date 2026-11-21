import { api } from './client'
import type {
  SubtitleLoadRequest,
  SubtitleLoadResponse,
  SubtitleExportRequest,
  SubtitleExportResponse,
  ScriptToSubtitleRequest,
  TaskStatusResponse,
  ScriptPreview,
  ScriptReview,
} from './types'

export const subtitlesApi = {
  load: (body: SubtitleLoadRequest) =>
    api.post<SubtitleLoadResponse>('/subtitles/load', body),

  export: (body: SubtitleExportRequest) =>
    api.post<SubtitleExportResponse>('/subtitles/export', body),

  createScriptTask: (body: ScriptToSubtitleRequest) =>
    api.post<TaskStatusResponse>('/subtitles/script-to-subtitle/tasks', body),

  previewScript: (body: ScriptToSubtitleRequest) =>
    api.post<ScriptPreview>('/subtitles/script-preview', body),

  scriptReview: (taskId: string) =>
    api.get<{ review: ScriptReview | null }>(`/subtitles/script-to-subtitle/tasks/${encodeURIComponent(taskId)}/review`),
}
