import { api } from './client'
import type { TranslateRequest, TranslateResponse } from './types'

export const translationApi = {
  translate: (body: TranslateRequest) =>
    api.post<TranslateResponse>('/llm/translate', body),
}
