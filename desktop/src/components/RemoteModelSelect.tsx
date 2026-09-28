import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'

interface Props {
  provider: string
  value: string
  onChange: (value: string) => void
  connectionRef?: string
}

/** Catalog results belong to the selected endpoint; never substitute a static list. */
export default function RemoteModelSelect({ provider, value, onChange, connectionRef }: Props) {
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)

  useEffect(() => {
    generation.current += 1
    setModels([])
    setError('')
    setLoading(false)
    return () => { generation.current += 1 }
  }, [provider, connectionRef])

  const refresh = async () => {
    const request = ++generation.current
    setLoading(true)
    setError('')
    try {
      const response = await settingsApi.listModels(provider,
        connectionRef ? { active_connections: { llm: connectionRef } } : undefined)
      if (request !== generation.current) return
      setModels(response.models)
      if (response.models.length === 0) setError('服务未返回模型列表，请到设置中核对。')
    } catch (cause) {
      if (request !== generation.current) return
      setModels([])
      setError(cause instanceof Error ? cause.message : '获取模型失败')
    } finally {
      if (request === generation.current) setLoading(false)
    }
  }

  const choices = Array.from(new Set([value, ...models].filter(Boolean)))
  return (
    <div style={{ display: 'grid', gap: 8, fontSize: 13 }}>
      <label htmlFor="translation-model">翻译模型</label>
      <div style={{ display: 'flex', gap: 8 }}>
        <select id="translation-model" value={value} onChange={event => onChange(event.target.value)}
          style={{ flex: 1, minWidth: 0, padding: '10px 12px', borderRadius: 'var(--radius-button)', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)' }}>
          {!value && <option value="">使用服务默认模型</option>}
          {choices.map(model => <option key={model} value={model}>{model}</option>)}
        </select>
        <button type="button" onClick={() => void refresh()} disabled={loading}
          style={{ padding: '8px 12px', borderRadius: 'var(--radius-button)', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)', whiteSpace: 'nowrap' }}>
          {loading ? '获取中…' : '获取模型'}
        </button>
      </div>
      {error && <span role="alert" style={{ fontSize: 12, color: 'var(--muted)' }}>{error}</span>}
    </div>
  )
}
