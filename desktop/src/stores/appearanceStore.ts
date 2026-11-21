import { create } from 'zustand'

export type Language = 'zh-CN' | 'en'
export type ThemeMode = 'light' | 'dark' | 'system' | 'custom'
export type SurfaceBase = 'light' | 'dark'
export const APPEARANCE_KEY = 'asmr-helper.appearance.v1'
export const BACKGROUND_KEY = 'asmr-helper.background.v1'
type Preferences = {
  language: Language
  overlay: number
  theme: ThemeMode
  customSurface: SurfaceBase
  accentColor: string
}
type Background = { name: string; data: string }
const VALID_THEMES: ThemeMode[] = ['light', 'dark', 'system', 'custom']
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/
const defaults: Preferences = {
  language: 'zh-CN',
  overlay: 0.78,
  theme: 'light',
  customSurface: 'light',
  accentColor: '#117f8d',
}

export function readPreferences(): Preferences {
  try {
    const value = JSON.parse(localStorage.getItem(APPEARANCE_KEY) || '{}')
    return {
      language: value?.language === 'en' ? 'en' : 'zh-CN',
      overlay: typeof value?.overlay === 'number' && Number.isFinite(value.overlay)
        ? Math.min(0.94, Math.max(0.72, value.overlay)) : defaults.overlay,
      theme: VALID_THEMES.includes(value?.theme) ? value.theme : defaults.theme,
      customSurface: value?.customSurface === 'dark' ? 'dark' : defaults.customSurface,
      accentColor: typeof value?.accentColor === 'string' && HEX_COLOR.test(value.accentColor)
        ? value.accentColor : defaults.accentColor,
    }
  } catch { return defaults }
}

function readBackground(): { background: Background | null; issue: string } {
  try {
    const raw = localStorage.getItem(BACKGROUND_KEY)
    if (!raw) return { background: null, issue: '' }
    const value = JSON.parse(raw)
    if (typeof value?.name !== 'string' || typeof value?.data !== 'string'
      || value.data.length > 2_000_000 || !value.data.startsWith('data:image/jpeg;base64,')) throw new Error()
    return { background: value, issue: '' }
  } catch { return { background: null, issue: 'backgroundUnavailable' } }
}

interface AppearanceState extends Preferences {
  background: Background | null
  issue: string
  setPreferences: (patch: Partial<Preferences>) => boolean
  setBackground: (background: Background | null) => boolean
  markBackgroundUnavailable: () => void
}

export const useAppearanceStore = create<AppearanceState>((set, get) => ({
  ...readPreferences(), ...readBackground(),
  setPreferences: patch => {
    const current = get()
    const next: Preferences = {
      language: patch.language ?? current.language,
      overlay: Math.min(0.94, Math.max(0.72, patch.overlay ?? current.overlay)),
      theme: patch.theme && VALID_THEMES.includes(patch.theme) ? patch.theme : current.theme,
      customSurface: patch.customSurface === 'dark' || patch.customSurface === 'light' ? patch.customSurface : current.customSurface,
      accentColor: patch.accentColor && HEX_COLOR.test(patch.accentColor) ? patch.accentColor : current.accentColor,
    }
    try { localStorage.setItem(APPEARANCE_KEY, JSON.stringify(next)); set({ ...next, issue: current.issue === 'storageFailed' ? '' : current.issue }); return true }
    catch { set({ issue: 'storageFailed' }); return false }
  },
  setBackground: background => {
    try {
      if (background) localStorage.setItem(BACKGROUND_KEY, JSON.stringify(background))
      else localStorage.removeItem(BACKGROUND_KEY)
      set({ background, issue: '' }); return true
    } catch { set({ issue: 'storageFailed' }); return false }
  },
  markBackgroundUnavailable: () => set({ background: null, issue: 'backgroundUnavailable' }),
}))

/** Decode locally and store a bounded, metadata-free copy, never a temporary file URL. */
export async function prepareBackground(file: File): Promise<Background> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 20 * 1024 * 1024) {
    throw new Error('invalidImage')
  }
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    if (!image.naturalWidth || !image.naturalHeight || image.naturalWidth * image.naturalHeight > 80_000_000) throw new Error('invalidImage')
    const scale = Math.min(1, 1920 / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('invalidImage')
    context.fillStyle = '#f5f8fa'; context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const data = canvas.toDataURL('image/jpeg', 0.82)
    if (data.length > 2_000_000) throw new Error('invalidImage')
    return { name: file.name, data }
  } catch { throw new Error('invalidImage') }
  finally { URL.revokeObjectURL(url) }
}
