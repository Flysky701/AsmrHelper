import { api } from './client'
import type {
  SubtitleLoadRequest,
  SubtitleLoadResponse,
  SubtitleExportRequest,
  SubtitleExportResponse,
  SubtitleTranslationRequest,
  SubtitleTranslationResponse,
  ScriptToVttRequest,
  ScriptToVttResponse,
} from './types'

export const subtitlesApi = {
  load: (body: SubtitleLoadRequest) =>
    api.post<SubtitleLoadResponse>('/subtitles/load', body),

  export: (body: SubtitleExportRequest) =>
    api.post<SubtitleExportResponse>('/subtitles/export', body),

  translate: (body: SubtitleTranslationRequest) =>
    api.post<SubtitleTranslationResponse>('/subtitles/translate', body),

  scriptToVtt: (body: ScriptToVttRequest) =>
    api.post<ScriptToVttResponse>('/subtitles/script-to-vtt', body),
}
