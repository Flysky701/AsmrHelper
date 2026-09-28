import { api } from './client'
import type {
  SubtitleLoadRequest,
  SubtitleLoadResponse,
  SubtitleExportRequest,
  SubtitleExportResponse,
  ScriptToSubtitleRequest,
  TaskStatusResponse,
} from './types'

export const subtitlesApi = {
  load: (body: SubtitleLoadRequest) =>
    api.post<SubtitleLoadResponse>('/subtitles/load', body),

  export: (body: SubtitleExportRequest) =>
    api.post<SubtitleExportResponse>('/subtitles/export', body),

  createScriptTask: (body: ScriptToSubtitleRequest) =>
    api.post<TaskStatusResponse>('/subtitles/script-to-subtitle/tasks', body),
}
