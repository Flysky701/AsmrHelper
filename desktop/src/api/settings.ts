import { api } from './client'

export interface ProviderSettings {
  base_url: string
  credential_configured: boolean
  /** Write-only. It is never returned by the backend. */
  credential?: string
}

export interface SettingsView {
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

export const settingsApi = {
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
