import { api } from './client'
import type { TtsVoicesResponse } from './types'

export const ttsApi = {
  listVoices: (engineId: string) =>
    api.get<TtsVoicesResponse>(`/tts/engines/${encodeURIComponent(engineId)}/voices`),

}
