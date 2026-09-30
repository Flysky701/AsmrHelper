import type { SpeechProvider } from '@/api/speech'

export function availableSpeechOptions(provider: SpeechProvider | undefined, mode: string, model = '') {
  return Object.entries(provider?.options_schema.properties || {}).filter(([key, field]) => key !== 'schema_version' && field.const === undefined
    && (!field.applies_to_modes || field.applies_to_modes.includes(mode))
    && !(provider?.provider_id === 'fish_audio' && model === 's1' && key === 'style_description'))
}

export function unsupportedSpeechOptions(provider: SpeechProvider | undefined, mode: string, values: Record<string, unknown>, model = '') {
  const fields = availableSpeechOptions(provider, mode, model)
  return Object.keys(values).filter(key => {
    if (key === 'schema_version' || fields.some(([name]) => key === name)) return false
    const field = provider?.options_schema.properties[key]
    return !(field && values[key] === field.default && (values[key] === false || values[key] === ''))
  })
}

export function speechOptionsIssue(provider: SpeechProvider | undefined, mode: string, values: Record<string, unknown>, model = ''): string {
  if (!provider) return ''
  const fields = availableSpeechOptions(provider, mode, model)
  const unknown = unsupportedSpeechOptions(provider, mode, values, model)
  if (unknown.length) return `当前引擎或模式不支持参数：${unknown.join('、')}。请移除后再使用。`
  for (const [key, field] of fields) {
    const value = values[key]
    if (value === undefined) continue
    const title = field.title || key
    if (field.type === 'boolean' && typeof value !== 'boolean') return `${title}必须为开或关。`
    if (field.type === 'number' || field.type === 'integer') {
      if (typeof value !== 'number' || !Number.isFinite(value) || (field.type === 'integer' && !Number.isInteger(value))) return `${title}需要有效${field.type === 'integer' ? '整数' : '数字'}。`
      if ((field.minimum !== undefined && value < field.minimum) || (field.maximum !== undefined && value > field.maximum)) return `${title}超出允许范围。`
    }
    if (field.maxLength !== undefined && String(value).length > field.maxLength) return `${title}最多${field.maxLength}字。`
    if (field.enum && !field.enum.includes(value as string | number)) return `${title}不在可选范围。`
  }
  return ''
}

export function speechLanguageMatches(saved: string, target: string): boolean {
  const base = (value: string) => value.toLowerCase().replace('_', '-').split('-')[0]
  return !saved || saved === 'auto' || base(saved) === base(target)
}
