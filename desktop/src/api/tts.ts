import { api } from './client'
import type { SynthesizeRequest, SynthesizeResponse } from './types'

export const ttsApi = {
  synthesize: (body: SynthesizeRequest) =>
    api.post<SynthesizeResponse>('/tts/synthesize', body),
}
