import type { SpeechConnection, SpeechConnectionDefault } from '@/api/speech'

/** Only an explicit engine default is selected; neither list order nor a sole entry is evidence. */
export function defaultSpeechConnection(providerId: string, connections: SpeechConnection[], defaults: SpeechConnectionDefault[]): SpeechConnection | undefined {
  const selected = defaults.find(item => item.provider_id === providerId)?.connection_ref
  return selected ? connections.find(item => item.id === selected && item.provider_id === providerId) : undefined
}

export const connectionDeploymentNames = { local: '本机', lan: '局域网', cloud: '云端' }
