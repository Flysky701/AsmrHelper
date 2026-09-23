import { api } from './client'

export interface ProviderSettings {
  base_url: string
  model: string
  credential_configured: boolean
  /** Write-only. It is never returned by the backend. */
  credential?: string
}

export interface ConnectionProfile {
  id: string
  name: string
  provider: string
  base_url: string
  model?: string
  api_format?: 'speech' | 'mimo_chat' | 'fish'
  voice?: string
  instructions?: string
  credential_configured: boolean
}

export interface SettingsView {
  connection_profiles: {
    llm: ConnectionProfile[]
    tts: ConnectionProfile[]
    active_llm: string
    active_tts: string
  }
  external_tts: {
    base_url: string
    model: string
    voice: string
    api_format: 'speech' | 'mimo_chat' | 'fish'
    instructions: string
    credential_configured: boolean
  }
  providers: {
    default_llm: string
    deepseek: ProviderSettings
    openai: ProviderSettings
  }
  tts: {
    engine: string
    voice: string
    speed: number
  }
  paths: {
    output_dir: string
    vtt_dir: string
    model_cache_dir: string
    temp_dir: string
  }
  processing: {
    original_volume: number
    tts_volume: number
    tts_delay: number
    vocal_model: string
    asr_model: string
  }
}

export interface SettingsResponse {
  settings: SettingsView
}

export type SettingsUpdate = {
  connection_profile?: {
    kind: 'llm' | 'tts'
    id?: string
    name: string
    provider?: string
    base_url?: string
    model?: string
    api_format?: 'speech' | 'mimo_chat' | 'fish'
    voice?: string
    instructions?: string
    credential?: string
  }
  active_connections?: { llm?: string; tts?: string }
  external_tts?: Partial<SettingsView['external_tts']> & { credential?: string }
  providers?: {
    default_llm?: string
    deepseek?: Partial<ProviderSettings>
    openai?: Partial<ProviderSettings>
  }
  tts?: Partial<SettingsView['tts']>
  paths?: Partial<SettingsView['paths']>
  processing?: Partial<SettingsView['processing']>
}

export interface ValidateResponse {
  valid: boolean
  errors: string[]
  settings: SettingsView
}

export interface TestProviderResponse {
  provider: string
  success: boolean
  error_code: string | null
  message: string
  errors: string[]
}

export interface ProviderModelsResponse {
  provider: string
  models: string[]
}

export const settingsApi = {
  listModels: (provider: string, settings?: SettingsUpdate) =>
    api.post<ProviderModelsResponse>('/settings/models', {
      provider,
      settings: settings ?? {},
    }),

  get: () => api.get<SettingsResponse>('/settings'),

  update: (settings: SettingsUpdate) =>
    api.put<SettingsResponse>('/settings', { settings }),

  validate: (settings?: SettingsUpdate) =>
    api.post<ValidateResponse>('/settings/validate', { settings: settings ?? {} }),

  testProvider: (provider: string, settings?: SettingsUpdate) =>
    api.post<TestProviderResponse>('/settings/test-provider', {
      provider,
      settings: settings ?? {},
    }),
}
