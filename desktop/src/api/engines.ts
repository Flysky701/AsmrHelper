import { api } from './client'

export interface EngineDescriptor {
    id: string
    name: string
    status: string
    capabilities?: string[]
}

export interface EngineListResponse {
    engines: EngineDescriptor[]
}

export interface ProviderDescriptor {
    id: string
    name: string
    status: string
    models?: string[]
}

export interface ProviderListResponse {
    providers: ProviderDescriptor[]
}

export const enginesApi = {
    ttsEngines: () => api.get<EngineListResponse>('/tts/engines'),
    asrEngines: () => api.get<EngineListResponse>('/asr/engines'),
    llmProviders: () => api.get<ProviderListResponse>('/llm/providers'),
}
