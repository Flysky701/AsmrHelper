import type { SpeechConnection, SpeechConnectionDefault, SpeechProvider } from '@/api/speech'
import { speechProviderBaseUrl } from './speechAdvancedOptions'

/** Only an explicit engine default is selected; neither list order nor a sole entry is evidence. */
export function defaultSpeechConnection(providerId: string, connections: SpeechConnection[], defaults: SpeechConnectionDefault[]): SpeechConnection | undefined {
  const selected = defaults.find(item => item.provider_id === providerId)?.connection_ref
  return selected ? connections.find(item => item.id === selected && item.provider_id === providerId) : undefined
}

export const connectionDeploymentNames = { local: '本机', lan: '局域网', cloud: '云端' }

export function speechConnectionDraftForProvider(current: Pick<SpeechConnection, 'name'> & Partial<Pick<SpeechConnection, 'id'>>, provider: SpeechProvider) {
  return {
    name: current.id ? '' : current.name,
    provider_id: provider.provider_id,
    deployment: provider.connection_deployments?.[0] ?? 'cloud',
    base_url: speechProviderBaseUrl(provider),
    api_key: '',
  }
}
