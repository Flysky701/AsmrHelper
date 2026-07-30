import { api } from './client'
import type { SynthesizeRequest, SynthesizeResponse, TtsVoicesResponse } from './types'

export const ttsApi = {
  listVoices: (engineId: string) =>
    api.get<TtsVoicesResponse>(`/tts/engines/${encodeURIComponent(engineId)}/voices`),

  synthesize: (body: SynthesizeRequest) =>
    api.post<SynthesizeResponse>('/tts/synthesize', body),
}
