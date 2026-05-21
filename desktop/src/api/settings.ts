import { api } from './client'

export interface SettingsResponse {
    api: {
        provider: string
        deepseek_api_key: string
        openai_api_key: string
        deepseek_base_url: string
        openai_base_url: string
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

export interface ValidateResponse {
    valid: boolean
    errors: string[]
    settings: SettingsResponse
}

export interface TestProviderResponse {
    success: boolean
    errors: string[]
}

export const settingsApi = {
    get: () => api.get<SettingsResponse>('/settings'),

    update: (body: Partial<SettingsResponse>) =>
        api.post<SettingsResponse>('/settings', body),

    validate: (body?: Partial<SettingsResponse>) =>
        api.post<ValidateResponse>('/settings/validate', body ?? {}),

    testProvider: (provider: string, settings?: Partial<SettingsResponse>) =>
        api.post<TestProviderResponse>('/settings/test-provider', { provider, ...(settings ?? {}) }),
}
