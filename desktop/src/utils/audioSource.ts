import { convertFileSrc, isTauri } from '@tauri-apps/api/core'

const URL_SCHEME = /^[a-z][a-z\d+.-]*:\/\//i

export function toPlayableAudioSource(source: string): string {
  const value = source.trim()
  if (!value || URL_SCHEME.test(value) || value.startsWith('blob:') || value.startsWith('data:')) {
    return value
  }
  return isTauri() ? convertFileSrc(value) : value
}
