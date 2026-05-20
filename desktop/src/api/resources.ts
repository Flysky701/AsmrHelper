import { api } from './client'
import type { ResourceStatusListResponse } from './types'

export const resourcesApi = {
  getStatus: () => api.get<ResourceStatusListResponse>('/resources/status'),
}
