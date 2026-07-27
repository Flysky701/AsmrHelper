import { api } from './client'
import type { CapabilityDescriptorResponse } from './types'

export const capabilitiesApi = {
  list: (category?: string) =>
    api.get<CapabilityDescriptorResponse[]>(
      category ? `/capabilities?category=${encodeURIComponent(category)}` : '/capabilities',
    ),
}
