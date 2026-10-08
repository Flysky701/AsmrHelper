import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import type { ConnectionProfile, ConnectionRemovalPreview, SettingsUpdate, SettingsView } from '@/api/settings'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import SpeechConnections from './SpeechConnections'
import { useConnectionDraftGuard } from '@/hooks/useConnectionDraftGuard'

type Kind = 'llm'
type Editor = ConnectionProfile & { kind: Kind; credential: string }
type Discovery = { success: boolean; message: string; models: string[] }
// Legacy settings synthesize default provider records even before the user adds a service.
function isSavedProfile(profile: ConnectionProfile) {
  if (!profile.id.startsWith('legacy-') || profile.credential_configured) return true
  const defaults: Record<string, { name: string; urls: string[] }> = {
    'legacy-deepseek': { name: 'DeepSeek', urls: ['', 'https://api.deepseek.com', 'https://api.deepseek.com/v1'] },
    'legacy-openai': { name: 'OpenAI 兼容', urls: ['', 'https://api.openai.com/v1'] },
  }
  const preset = defaults[profile.id]
  return !preset || profile.name !== preset.name || !preset.urls.includes(profile.base_url.replace(/\/+$/, ''))
}

export default function ExternalServices() {
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [editor, setEditor] = useState<Editor | null>(null)
  const [testing, setTesting] = useState(false)
  const [discovery, setDiscovery] = useState<Discovery | null>(null)
  const [verified, setVerified] = useState<Record<string, string>>({})
  const [removal, setRemoval] = useState<ConnectionRemovalPreview | null>(null)
  const mutationRef = useRef(false)
  const loadGeneration = useRef(0)
  const discoveryGeneration = useRef(0)
  const editorBaseline = useRef('')
  const canDiscard = useConnectionDraftGuard({ dirty: !!editor && JSON.stringify(editor) !== editorBaseline.current,
    busy: saving || testing, onBlocked: setMessage })

  useEffect(() => {
    void load()
    return () => { loadGeneration.current += 1; discoveryGeneration.current += 1 }
  }, [])

  async function load() {
    const generation = ++loadGeneration.current
    setLoading(true)
    setError('')
    try {
      const result = await settingsApi.get()
      if (generation === loadGeneration.current) setSettings(result.settings)
    } catch (cause) {
      if (generation === loadGeneration.current) setError(`无法加载外部服务：${String(cause)}`)
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }

  function resetDiscovery() {
    discoveryGeneration.current += 1
    setTesting(false)
    setDiscovery(null)
  }

  async function edit(kind: Kind, profile?: ConnectionProfile) {
    if (!(await canDiscard())) return
    resetDiscovery()
    setMessage('')
    const next = { kind, credential: '', ...(profile ?? {
      id: '', name: '', provider: 'deepseek',
      base_url: 'https://api.deepseek.com', model: '', credential_configured: false,
    }) }
    editorBaseline.current = JSON.stringify(next)
    setEditor(next)
  }

  function candidate(current: Editor): SettingsUpdate {
    const legacy = !current.id && settings?.connection_profiles[current.kind].find(profile =>
      !isSavedProfile(profile) && profile.provider === current.provider && profile.name.toLowerCase() === current.name.trim().toLowerCase())
    const id = current.id || (legacy ? legacy.id : '')
    return { connection_profile: {
      kind: current.kind, ...(id ? { id } : {}), name: current.name.trim(),
      provider: current.provider, base_url: current.base_url.trim(),
      model: current.model?.trim() || '',
      ...(current.credential ? { credential: current.credential } : {}),
    } }
  }

  function syncWorkbench(current: SettingsView) {
    const workbench = useWorkbenchStore.getState()
    const provider = current.providers.default_llm === 'deepseek' ? 'deepseek' : 'openai'
    workbench.updateParam('translateProvider', provider)
    workbench.updateParam('translateModel', current.providers[provider].model)
  }

  async function save() {
    if (!editor) return
    if (!editor.name.trim()) { setMessage('保存失败：请填写配置名称'); return }
    if (editor.kind === 'llm' && !editor.model?.trim()) {
      setMessage('保存失败：请获取并选择模型，或根据服务商文档手动填写模型'); return
    }
    setSaving(true)
    setMessage('')
    try {
      const result = await settingsApi.update(candidate(editor))
      setSettings(result.settings)
      syncWorkbench(result.settings)
      const id = result.settings.connection_profiles.active_llm
      setVerified(previous => ({ ...previous, [id]: editor.kind === 'llm' && discovery?.success ? '已获取模型' : '' }))
      resetDiscovery()
      setEditor(null)
      setMessage('配置已保存并启用，用于新任务')
    } catch (cause) { setMessage(`保存失败：${String(cause)}`) }
    finally { setSaving(false) }
  }

  async function activate(kind: Kind, id: string) {
    setSaving(true)
    setMessage('')
    try {
      const result = await settingsApi.update({ active_connections: { [kind]: id } })
      setSettings(result.settings)
      syncWorkbench(result.settings)
      setMessage('配置已启用，用于新任务')
    } catch (cause) { setMessage(`启用失败：${String(cause)}`) }
    finally { setSaving(false) }
  }

  async function inspectRemoval(profile: ConnectionProfile) {
    if (mutationRef.current || !(await canDiscard())) return
    mutationRef.current = true
    setSaving(true); setMessage(''); setRemoval(null)
    try {
      const preview = await settingsApi.connectionRemovalPreview(profile.id)
      if (preview.id !== profile.id) throw new Error('连接预览归属不匹配')
      setEditor(null); resetDiscovery(); setRemoval(preview)
    } catch { setMessage('无法读取连接删除影响，请刷新后重试。') }
    finally { mutationRef.current = false; setSaving(false) }
  }

  async function changeRemoval() {
    if (!removal || mutationRef.current || !removal.can_remove) return
    mutationRef.current = true
    setSaving(true); setMessage('')
    const reviewed = removal
    try {
      const result = await settingsApi.deleteConnection(reviewed.id, reviewed.token)
      loadGeneration.current += 1
      setSettings(result.settings); setRemoval(null)
      setMessage('连接及其独有本地凭据已删除，无法撤销。云端账号和历史快照保留。')
    } catch (cause) {
      setRemoval(null); setMessage(`操作未确认完成，请刷新并重新检查：${String(cause)}`)
    } finally { mutationRef.current = false; setSaving(false) }
  }

  async function discover() {
    if (!editor || editor.kind !== 'llm') return
    const generation = ++discoveryGeneration.current
    setTesting(true)
    setDiscovery(null)
    try {
      const result = await settingsApi.listModels(editor.provider, candidate({ ...editor, name: editor.name.trim() || '未命名翻译配置' }))
      if (generation !== discoveryGeneration.current) return
      const models = [...new Set(result.models)]
      setDiscovery({ success: models.length > 0, models, message: models.length
        ? `已获取 ${models.length} 个模型，请选择用于翻译的模型。`
        : '服务未返回可选模型。可重试，或根据服务商文档手动填写。' })
    } catch (cause) {
      if (generation === discoveryGeneration.current) setDiscovery({ success: false, models: [], message: `获取模型失败：${String(cause)}` })
    } finally { if (generation === discoveryGeneration.current) setTesting(false) }
  }

  if (loading) return <p style={{ color: 'var(--muted)' }}>加载外部服务中...</p>
  if (!settings) return <div role="alert"><p>{error}</p><button onClick={() => void load()}>重新加载</button></div>

  const profiles = {
    active_llm: settings.connection_profiles.active_llm,
    llm: settings.connection_profiles.llm.filter(isSavedProfile),
  }
  const editorForm = (kind: Kind) => editor?.kind === kind && (
    <fieldset disabled={saving} className="external-service-editor">
      <div className="external-service-card-heading">
        <h3>{editor.id ? '编辑配置' : '添加翻译服务'}</h3>
        <button className="external-service-button" onClick={async () => { if (await canDiscard()) { resetDiscovery(); setEditor(null) } }}>收起</button>
      </div>
      <label className="external-service-field">配置名称
        <input value={editor.name} maxLength={80} onChange={event => setEditor({ ...editor, name: event.target.value })} placeholder="例如：日常翻译" />
      </label>
      <label className="external-service-field">服务提供商
        <select value={editor.provider} disabled={!!editor.id} onChange={event => {
          resetDiscovery()
          setEditor({ ...editor, provider: event.target.value, base_url: event.target.value === 'deepseek' ? 'https://api.deepseek.com' : '', credential: '', model: '' })
        }}><option value="deepseek">DeepSeek</option><option value="openai">OpenAI / 兼容接口</option></select>
      </label>
      <label className="external-service-field">API 地址
        <input value={editor.base_url} onChange={event => {
          resetDiscovery()
          const base_url = event.target.value
          setEditor({ ...editor, base_url })
        }} placeholder="填写服务商提供的 API 基础地址" />
      </label>
      <label className="external-service-field">API 密钥
        <input type="password" autoComplete="off" value={editor.credential} onChange={event => { resetDiscovery(); setEditor({ ...editor, credential: event.target.value }) }} placeholder={editor.credential_configured ? '已配置；留空保持此配置的密钥' : '输入 API 密钥'} />
      </label>
      <>
        <button className="external-service-button" disabled={testing} onClick={() => void discover()}>{testing ? '检测中...' : '检测连接并获取模型'}</button>
        {discovery && <p role="status" className="external-service-muted" style={{ color: discovery.success ? 'var(--accent)' : 'var(--danger)' }}>{discovery.message}</p>}
        <label className="external-service-field" style={{ marginTop: 16 }}>翻译模型
          <select value={editor.model || ''} onChange={event => setEditor({ ...editor, model: event.target.value })}>
            <option value="">{discovery?.models.length ? '选择模型' : '获取模型后选择'}</option>
            {editor.model && !discovery?.models.includes(editor.model) && <option value={editor.model}>{editor.model}（未核验）</option>}
            {discovery?.models.map(model => <option key={model} value={model}>{model}</option>)}
          </select>
        </label>
        <details><summary>手动填写模型</summary><label className="external-service-field" style={{ marginTop: 12 }}>服务商文档中的模型 ID
          <input value={editor.model || ''} onChange={event => setEditor({ ...editor, model: event.target.value })} placeholder="填写文档中支持翻译的模型 ID" />
        </label></details>
      </>
      <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
        <button className="external-service-button external-service-primary" disabled={testing} onClick={() => void save()}>{saving ? '保存中...' : '保存并启用'}</button>
        <button className="external-service-button" onClick={async () => { if (await canDiscard()) { resetDiscovery(); setEditor(null) } }}>取消</button>
      </div>
    </fieldset>
  )

  return <div className="external-services">
    {message && <div className="external-service-notice" role="status">{message}</div>}
    {removal && <section className="external-service-notice" aria-label="翻译连接删除影响">
      <h3>删除「{removal.name}」</h3>
      <p>删除本地连接记录及独有凭据，不删除文件或云端账号；历史快照保留。无法撤销。</p>
      {removal.active && <p role="alert">此连接当前已启用，请先在列表中启用另一条连接。</p>}
      {!!removal.references.length && <><p>以下引用需要先处理；保存的工作流需重新选择连接，活动任务或批次需等待结束。</p><ul>{removal.references.map(item =>
        <li key={`${item.kind}:${item.id}`}>{({ workflow: '工作流', task: '活动任务', batch: '活动批次' })[item.kind]}：{item.name}</li>)}</ul></>}
      <button className="external-service-button" disabled={saving || !removal.can_remove} onClick={() => void changeRemoval()}>确认删除</button>
      <button className="external-service-button" disabled={saving} onClick={() => setRemoval(null)}>取消</button>
    </section>}
    {(['llm'] as const).map(kind => <section className="external-service-section" key={kind}>
      <div className="external-service-heading">
        <span className="external-service-tag">{kind.toUpperCase()}</span>
        <h2>翻译服务</h2>
        <button className="external-service-button" disabled={saving} onClick={() => edit(kind)}>添加服务</button>
      </div>
      <div className="external-service-body">
        {profiles[kind].length === 0 && <p className="external-service-muted">尚未添加翻译服务</p>}
        {profiles[kind].map(profile => {
          const active = profile.id === profiles.active_llm
          return <div className="external-service-card" key={profile.id}>
            <div className="external-service-card-heading">
              <h3>{profile.name}</h3>
              {active && <span className="external-service-active">已启用</span>}
              <div className="external-service-actions">
                {!active && <button className="external-service-button" disabled={saving} onClick={() => void activate(kind, profile.id)}>启用</button>}
                <button className="external-service-button" aria-expanded={editor?.kind === kind && editor.id === profile.id} disabled={saving} onClick={() => edit(kind, profile)}>编辑</button>
                <button className="external-service-button" disabled={saving} onClick={() => void inspectRemoval(profile)}>删除…</button>
              </div>
            </div>
            <p className="external-service-muted">{`${profile.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI / 兼容接口'} · ${profile.model || '未选择模型'}`}</p>
            <div className="external-service-muted">{profile.credential_configured ? '密钥已配置' : '未配置密钥'} · {verified[profile.id] || '连接未验证'}</div>
            {editor?.kind === kind && editor.id === profile.id && editorForm(kind)}
          </div>
        })}
        {editor?.kind === kind && !editor.id && editorForm(kind)}
      </div>
    </section>)}
    {!!settings.connection_profiles.removed_llm?.length && <details className="external-service-notice"><summary>旧版保留连接</summary>
      {settings.connection_profiles.removed_llm.map(profile => <div key={profile.id} className="external-service-card-heading"><span>{profile.name}</span>
        <button className="external-service-button" disabled={saving} onClick={() => void inspectRemoval(profile)}>删除…</button></div>)}
    </details>}
    <SpeechConnections />
    <style>{`
      .external-services { max-width: 1040px; min-width: 0; }
      .external-service-section { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); margin-bottom: 20px; overflow: hidden; }
      .external-service-heading { display: flex; align-items: center; gap: 12px; padding: 18px 20px; background: var(--panel-muted); border-bottom: 1px solid var(--border); }
      .external-service-heading h2 { flex: 1; font-size: var(--text-section); margin: 0; font-weight: 600; line-height: 1.4; }
      .external-service-tag, .external-service-active { color: var(--accent); background: var(--accent-soft); border-radius: 6px; padding: 4px 8px; font-size: var(--text-help); font-weight: 600; }
      .external-service-body { padding: 16px 20px; }
      .external-service-card { padding: 16px; border: 1px solid var(--border); border-radius: 9px; margin-bottom: 12px; min-width: 0; }
      .external-service-card:last-child { margin-bottom: 0; }
      .external-service-card-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
      .external-service-card-heading h3 { font-size: var(--text-section); font-weight: 600; line-height: 1.4; margin: 0; overflow-wrap: anywhere; }
      .external-service-actions { margin-left: auto; display: flex; gap: 8px; }
      .external-service-muted { color: var(--muted); font-size: var(--text-help); line-height: 1.7; overflow-wrap: anywhere; }
      .external-service-editor { border: 0; border-top: 1px solid var(--border); margin: 18px 0 0; padding: 20px 0 0; min-width: 0; }
      .external-service-editor > .external-service-card-heading { justify-content: space-between; margin-bottom: 20px; }
      .external-service-field { display: grid; gap: 6px; font-size: var(--text-control); margin-bottom: 16px; }
      .external-service-field input, .external-service-field select, .external-service-field textarea { width: 100%; min-width: 0; font: inherit; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg); }
      .external-service-button { font: inherit; font-size: var(--text-control); padding: 8px 14px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg); cursor: pointer; }
      .external-service-button:disabled { opacity: .6; cursor: default; }
      .external-service-primary { background: var(--accent); border-color: var(--accent); color: white; }
      .external-service-editor summary { cursor: pointer; font-size: var(--text-help); color: var(--muted); }
      .external-service-notice { padding: 12px 16px; background: var(--panel-muted); border-radius: 8px; margin-bottom: 16px; font-size: var(--text-control); overflow-wrap: anywhere; }
      @media (max-width: 600px) { .external-service-heading { flex-wrap: wrap; padding: 14px; } .external-service-body { padding: 12px; } .external-service-heading h2 { font-size: var(--text-section); } }
    `}</style>
  </div>
}
