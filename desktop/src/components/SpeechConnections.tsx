import { useEffect, useRef, useState } from 'react'
import SpeechConnectionManager from './SpeechConnectionManager'
import { useConnectionDraftGuard } from '@/hooks/useConnectionDraftGuard'
import { speechApi } from '@/api/speech'
import type { SpeechConnection, SpeechConnectionDefault, SpeechProvider } from '@/api/speech'

type Editor = Partial<SpeechConnection> & { name: string; provider_id: string; deployment: SpeechConnection['deployment']; api_key: string }
const FISH_BASE_URL = 'https://api.fish.audio/v1'

export default function SpeechConnections() {
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [defaults, setDefaults] = useState<SpeechConnectionDefault[]>([])
  const loadGeneration = useRef(0)
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [checks, setChecks] = useState<Record<string, string>>({})
  const editorBaseline = useRef('')
  const canDiscard = useConnectionDraftGuard({ dirty: !!editor && JSON.stringify(editor) !== editorBaseline.current,
    busy: !!busy, onBlocked: setNotice })
  const lastLoadSucceeded = useRef(true)
  async function load() {
    const generation = ++loadGeneration.current
    lastLoadSucceeded.current = false
    setLoading(true)
    setError('')
    try {
      const [result, descriptors] = await Promise.all([speechApi.connections(), speechApi.providers()])
      if (generation !== loadGeneration.current) return
      lastLoadSucceeded.current = true
      setConnections(result.connections); setDefaults(result.defaults || [])
      setProviders(descriptors.providers.filter(item => item.connection_required))
    } catch (cause) { if (generation === loadGeneration.current) setError('无法加载语音服务：' + String(cause)) }
    finally { if (generation === loadGeneration.current) setLoading(false) }
  }
  useEffect(() => { void load(); return () => { loadGeneration.current++ } }, [])

  async function edit(connection?: SpeechConnection) {
    if (!(await canDiscard())) return
    setNotice('')
    const next: Editor = connection ? {
      id: connection.id, name: connection.name, provider_id: connection.provider_id,
      deployment: connection.deployment, base_url: connection.base_url || (connection.provider_id === 'fish_audio' ? FISH_BASE_URL : ''),
      credential_configured: connection.credential_configured, api_key: '',
    } : { name: '', provider_id: providers.find(item => item.provider_id === 'openai_compatible')?.provider_id || providers[0]?.provider_id || '', deployment: 'cloud', base_url: '', api_key: '' }
    editorBaseline.current = JSON.stringify(next)
    setEditor(next)
  }

  async function save() {
    if (!editor) return
    if (!editor.name.trim() || !editor.base_url?.trim()) {
      setNotice('请填写连接名称和 API 地址'); return
    }
    setBusy('保存中…')
    setNotice('')
    try {
      // Omit blank credentials and non-editable settings to preserve the saved connection.
      const saved = await speechApi.connection({
        ...(editor.id ? { id: editor.id } : {}), name: editor.name.trim(),
        provider_id: editor.provider_id, deployment: editor.provider_id === 'fish_audio' ? 'cloud' : editor.deployment,
        base_url: editor.base_url.trim(),
        ...(editor.api_key ? { api_key: editor.api_key } : {}),
      })
      setConnections(current => [...current.filter(item => item.id !== saved.id), saved])
      await load()
      setChecks(current => ({ ...current, [saved.id]: '' }))
      setEditor(null)
      setNotice(lastLoadSucceeded.current ? '语音服务已保存，可由声音与音色等功能引用。' : '语音服务已保存，但列表刷新失败。请重新加载核对，勿重复新增。')
    } catch (cause) { setNotice('保存失败：' + String(cause)) }
    finally { setBusy('') }
  }

  async function check(connection: SpeechConnection) {
    setBusy('检查中…')
    try {
      const result = await speechApi.probe(connection.id, '', '')
      setChecks(current => ({ ...current, [connection.id]: typeof result.detail === 'string' ? result.detail : result.ready ? '配置完整，尚未验证服务可达性' : '配置不完整' }))
    } catch (cause) { setChecks(current => ({ ...current, [connection.id]: '检查失败：' + String(cause) })) }
    finally { setBusy('') }
  }

  const external = connections.filter(connection => providers.some(provider => provider.provider_id === connection.provider_id))
  return <section className="external-service-section">
    <div className="external-service-heading">
      <span className="external-service-tag">TTS</span><h2>外部语音合成</h2>
      <button className="external-service-button" disabled={loading || !!busy || !providers.length} onClick={() => edit()}>添加服务</button>
    </div>
    <div className="external-service-body">
      <p className="external-service-muted">独立管理语音服务的接口与凭据。声音与音色可引用这里的连接，无需先创建音色。</p>
      {notice && <div className="external-service-notice" role="status">{notice}</div>}
      {loading ? <p className="external-service-muted">加载语音服务中…</p> : error ? <div role="alert"><p>{error}</p><button className="external-service-button" onClick={() => void load()}>重新加载</button></div> : <>
        {external.map(connection => <div className="external-service-card" key={connection.id}>
          <div className="external-service-card-heading"><h3>{connection.name}</h3><div className="external-service-actions">
            <button className="external-service-button" disabled={!!busy} onClick={() => void check(connection)}>检查配置</button>
            <button className="external-service-button" disabled={!!busy} aria-expanded={editor?.id === connection.id} onClick={() => edit(connection)}>编辑</button>
          </div></div>
          <p className="external-service-muted">{providers.find(provider => provider.provider_id === connection.provider_id)?.name} · {{ local: '本机服务', lan: '局域网', cloud: '云端' }[connection.deployment]}</p>
          <p className="external-service-muted">{connection.base_url}</p>
          <div className="external-service-muted" role="status">{connection.credential_configured ? '密钥已配置' : '未配置密钥'} · {checks[connection.id] || '服务可达性未验证'}</div>
        </div>)}
        {!external.length && !editor && <p className="external-service-muted">尚未添加外部语音服务</p>}
      </>}
      {!error && <details><summary>管理默认运行配置与删除</summary><SpeechConnectionManager protectNavigation connections={external} defaults={defaults} providers={providers} disabled={loading || !!busy} onChanged={load} /></details>}
      {editor && <fieldset disabled={!!busy} className="external-service-editor">
        <div className="external-service-card-heading"><h3>{editor.id ? '编辑语音服务' : '添加语音服务'}</h3><button className="external-service-button" onClick={async () => { if (await canDiscard()) setEditor(null) }}>收起</button></div>
        <label className="external-service-field">连接名称<input value={editor.name} maxLength={80} onChange={event => setEditor({ ...editor, name: event.target.value })} placeholder="例如：日常配音" /></label>
        <label className="external-service-field">接口协议<select value={editor.provider_id} disabled={!!editor.id} onChange={event => setEditor({ ...editor, provider_id: event.target.value, base_url: event.target.value === 'fish_audio' ? FISH_BASE_URL : '', deployment: 'cloud', api_key: '' })}>
          {providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
        </select></label>
        {editor.provider_id !== 'fish_audio' && <label className="external-service-field">运行位置<select value={editor.deployment} onChange={event => setEditor({ ...editor, deployment: event.target.value as SpeechConnection['deployment'] })}><option value="cloud">云端</option><option value="lan">局域网</option><option value="local">本机服务</option></select></label>}
        <label className="external-service-field">API 地址<input value={editor.base_url || ''} onChange={event => setEditor({ ...editor, base_url: event.target.value })} placeholder="填写服务商文档中的 API 基础地址" /></label>
        {editor.provider_id === 'fish_audio' && <p className="external-service-muted">已预填 Fish Audio 官方云端地址，可直接填写密钥保存。</p>}
        <label className="external-service-field">API 密钥<input type="password" autoComplete="off" value={editor.api_key} onChange={event => setEditor({ ...editor, api_key: event.target.value })} placeholder={editor.credential_configured ? '已配置；留空保持此连接的密钥' : '输入 API 密钥'} /></label>
        {editor.id && <p className="external-service-muted">更换 API 地址时需重新填写密钥。</p>}
        <div className="external-service-actions" style={{ marginTop: 20 }}><button className="external-service-button external-service-primary" onClick={() => void save()}>{busy || '保存服务'}</button><button className="external-service-button" onClick={async () => { if (await canDiscard()) setEditor(null) }}>取消</button></div>
      </fieldset>}
      <p className="external-service-muted">“检查配置”仅检查已保存的地址与凭据是否齐备，不会发起语音合成或验证服务可达性。</p>
    </div>
  </section>
}
