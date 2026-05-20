import { api } from './client'
import type {
  SubtitleLoadRequest,
  SubtitleLoadResponse,
  SubtitleExportRequest,
  SubtitleExportResponse,
  ScriptToVttRequest,
  ScriptToVttResponse,
} from './types'

export const subtitlesApi = {
  load: (body: SubtitleLoadRequest) =>
    api.post<SubtitleLoadResponse>('/subtitles/load', body),

  export: (body: SubtitleExportRequest) =>
    api.post<SubtitleExportResponse>('/subtitles/export', body),

  scriptToVtt: (body: ScriptToVttRequest) =>
    api.post<ScriptToVttResponse>('/subtitles/script-to-vtt', body),
}
