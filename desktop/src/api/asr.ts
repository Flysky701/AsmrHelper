import { api } from './client'
import type { TranscribeRequest, TranscribeResponse } from './types'

export const asrApi = {
  transcribe: (body: TranscribeRequest) =>
    api.post<TranscribeResponse>('/asr/transcribe', body),
}
