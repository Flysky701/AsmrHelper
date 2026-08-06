import { api } from './client'
import type {
  SubtitleLoadRequest,
  SubtitleLoadResponse,
  SubtitleExportRequest,
  SubtitleExportResponse,
  ScriptToVttRequest,
  TaskStatusResponse,
} from './types'

export const subtitlesApi = {
  load: (body: SubtitleLoadRequest) =>
    api.post<SubtitleLoadResponse>('/subtitles/load', body),

  export: (body: SubtitleExportRequest) =>
    api.post<SubtitleExportResponse>('/subtitles/export', body),

  createScriptTask: (body: ScriptToVttRequest) =>
    api.post<TaskStatusResponse>('/subtitles/script-to-vtt/tasks', body),
}
