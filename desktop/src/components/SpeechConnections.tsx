import { useEffect, useState } from 'react'
import { speechApi } from '@/api/speech'
import type { LegacySpeechImportReport, SpeechConnection, SpeechProvider } from '@/api/speech'

type Editor = Partial<SpeechConnection> & { name: string; provider_id: string; deployment: SpeechConnection['deployment']; api_key: string }
const FISH_BASE_URL = 'https://api.fish.audio/v1'

export default function SpeechConnections() {
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [checks, setChecks] = useState<Record<string, string>>({})
  const [legacyReport, setLegacyReport] = useState<LegacySpeechImportReport | null>(null)
  const [legacyError, setLegacyError] = useState('')

  async function loadLegacyReport() {
    try {
      setLegacyReport(await speechApi.legacyImportReport())
      setLegacyError('')
    } catch {
      setLegacyError('旧配置导入清单暂时无法读取，现有语音服务不受影响。')
    }
  }

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [library, descriptors] = await Promise.all([speechApi.library(), speechApi.providers()])
      setConnections(library.connections)
      setProviders(descriptors.providers.filter(item => item.connection_required))
    } catch (cause) { setError('无法加载语音服务：' + String(cause)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load(); void loadLegacyReport() }, [])

  async function importLegacy() {
    setBusy('导入中…')
    setLegacyError('')
    try {
      setLegacyReport(await speechApi.importLegacy())
      // Refresh only the connection list; importing never selects a service or changes a draft.
      try {
        setConnections((await speechApi.library()).connections)
        setNotice('旧配置导入已处理。请查看各项结果；需要使用时再选择导入的服务。')
      } catch {
        setLegacyError('导入已处理，但服务列表刷新失败，请重新加载列表查看。')
      }
    } catch {
      setLegacyError('旧配置导入未完成，请刷新清单后重试。')
    } finally { setBusy('') }
  }

  function edit(connection?: SpeechConnection) {
    setNotice('')
    setEditor(connection ? {
      id: connection.id, name: connection.name, provider_id: connection.provider_id,
      deployment: connection.deployment, base_url: connection.base_url || (connection.provider_id === 'fish_audio' ? FISH_BASE_URL : ''),
      credential_configured: connection.credential_configured, api_key: '',
    } : { name: '', provider_id: providers.find(item => item.provider_id === 'openai_compatible')?.provider_id || providers[0]?.provider_id || '', deployment: 'cloud', base_url: '', api_key: '' })
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
      setChecks(current => ({ ...current, [saved.id]: '' }))
      setEditor(null)
      setNotice('语音服务已保存，可由声音与音色等功能引用。')
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
      {editor && <fieldset disabled={!!busy} className="external-service-editor">
        <div className="external-service-card-heading"><h3>{editor.id ? '编辑语音服务' : '添加语音服务'}</h3><button className="external-service-button" onClick={() => setEditor(null)}>收起</button></div>
        <label className="external-service-field">连接名称<input value={editor.name} maxLength={80} onChange={event => setEditor({ ...editor, name: event.target.value })} placeholder="例如：日常配音" /></label>
        <label className="external-service-field">接口协议<select value={editor.provider_id} disabled={!!editor.id} onChange={event => setEditor({ ...editor, provider_id: event.target.value, base_url: event.target.value === 'fish_audio' ? FISH_BASE_URL : '', deployment: 'cloud', api_key: '' })}>
          {providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
        </select></label>
        {editor.provider_id !== 'fish_audio' && <label className="external-service-field">运行位置<select value={editor.deployment} onChange={event => setEditor({ ...editor, deployment: event.target.value as SpeechConnection['deployment'] })}><option value="cloud">云端</option><option value="lan">局域网</option><option value="local">本机服务</option></select></label>}
        <label className="external-service-field">API 地址<input value={editor.base_url || ''} onChange={event => setEditor({ ...editor, base_url: event.target.value })} placeholder="填写服务商文档中的 API 基础地址" /></label>
        {editor.provider_id === 'fish_audio' && <p className="external-service-muted">已预填 Fish Audio 官方云端地址，可直接填写密钥保存。</p>}
        <label className="external-service-field">API 密钥<input type="password" autoComplete="off" value={editor.api_key} onChange={event => setEditor({ ...editor, api_key: event.target.value })} placeholder={editor.credential_configured ? '已配置；留空保持此连接的密钥' : '输入 API 密钥'} /></label>
        {editor.id && <p className="external-service-muted">更换 API 地址时需重新填写密钥。</p>}
        <div className="external-service-actions" style={{ marginTop: 20 }}><button className="external-service-button external-service-primary" onClick={() => void save()}>{busy || '保存服务'}</button><button className="external-service-button" onClick={() => setEditor(null)}>取消</button></div>
      </fieldset>}
      <p className="external-service-muted">“检查配置”仅检查已保存的地址与凭据是否齐备，不会发起语音合成或验证服务可达性。</p>
      {legacyError && <div role="alert" className="external-service-muted"><p>{legacyError}</p><button className="external-service-button" disabled={!!busy} onClick={() => { void loadLegacyReport(); void load() }}>重新加载</button></div>}
      {!!legacyReport?.entries.length && <details className="external-service-muted">
        <summary>导入旧语音配置（{legacyReport.entries.length} 项）</summary>
        <p>仅新增可确认的服务连接，保留旧配置，不覆盖已有服务，也不改变当前选择。</p>
        {legacyReport.note && <p>{legacyReport.note}</p>}
        {legacyReport.entries.map((entry, index) => <div className="external-service-card" key={`${entry.source}-${index}`}>
          <div className="external-service-card-heading"><h3>{entry.name || '未命名旧配置'}</h3><span>{{ ready: '可导入', retained: '保留原配置', imported: '已导入' }[entry.status]}</span></div>
          <p>{providers.find(provider => provider.provider_id === entry.provider_id)?.name || entry.provider_id || '未识别的协议'} · {entry.credential_configured ? '密钥已配置' : '未配置密钥'}</p>
          {entry.reason && <p>{entry.reason}</p>}
          {!!entry.retained_fields.length && <p>保留在旧配置中的字段：{entry.retained_fields.join('、')}</p>}
        </div>)}
        {legacyReport.legacy_local_settings_retained && <p>旧本地引擎设置保留在原处，未自动转换。</p>}
        <button className="external-service-button" disabled={loading || !!busy || !legacyReport.entries.some(entry => entry.status === 'ready')} onClick={() => void importLegacy()}>{busy === '导入中…' ? busy : '导入可转换的服务'}</button>
      </details>}
    </div>
  </section>
}
