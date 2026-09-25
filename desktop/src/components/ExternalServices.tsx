import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import type { ConnectionProfile, SettingsUpdate, SettingsView } from '@/api/settings'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { speechApi } from '@/api/speech'
import type { SpeechConnection, SpeechProvider } from '@/api/speech'
import { useNavStore } from '@/stores/navStore'

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
  const [speechConnections, setSpeechConnections] = useState<SpeechConnection[]>([])
  const [speechProviders, setSpeechProviders] = useState<SpeechProvider[]>([])
  const [speechError, setSpeechError] = useState('')
  const [speechLoading, setSpeechLoading] = useState(true)
  const speechGeneration = useRef(0)
  const loadGeneration = useRef(0)
  const discoveryGeneration = useRef(0)

  useEffect(() => {
    void load()
    void loadSpeech()
    return () => { loadGeneration.current += 1; discoveryGeneration.current += 1; speechGeneration.current += 1 }
  }, [])

  async function loadSpeech() {
    const generation = ++speechGeneration.current
    setSpeechLoading(true)
    setSpeechError('')
    try {
      const [library, descriptors] = await Promise.all([speechApi.library(), speechApi.providers()])
      if (generation === speechGeneration.current) {
        setSpeechConnections(library.connections)
        setSpeechProviders(descriptors.providers)
      }
    } catch (cause) {
      if (generation === speechGeneration.current) setSpeechError('无法加载语音连接：' + String(cause))
    } finally { if (generation === speechGeneration.current) setSpeechLoading(false) }
  }

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

  function edit(kind: Kind, profile?: ConnectionProfile) {
    resetDiscovery()
    setMessage('')
    setEditor({ kind, credential: '', ...(profile ?? {
      id: '', name: '', provider: 'deepseek',
      base_url: 'https://api.deepseek.com', model: '', credential_configured: false,
    }) })
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
        <button className="external-service-button" onClick={() => { resetDiscovery(); setEditor(null) }}>收起</button>
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
        <button className="external-service-button" onClick={() => { resetDiscovery(); setEditor(null) }}>取消</button>
      </div>
    </fieldset>
  )

  return <div className="external-services">
    {message && <div className="external-service-notice" role="status">{message}</div>}
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
    <section className="external-service-section">
      <div className="external-service-heading">
        <span className="external-service-tag">TTS</span>
        <h2>外部语音合成</h2>
        <button className="external-service-button" onClick={() => useNavStore.getState().setPage('voice-lab')}>管理声音与音色</button>
      </div>
      <div className="external-service-body">
        <p className="external-service-muted">在「声音与音色」中管理参考录音和音色生成规则，工作台调用已保存的音色。</p>
        {speechLoading ? <p className="external-service-muted">加载语音连接中…</p> : speechError ? <div role="alert"><p className="external-service-muted">{speechError}</p><button className="external-service-button" onClick={() => void loadSpeech()}>重新加载</button></div> : <>
          {speechConnections.filter(connection => speechProviders.some(provider => provider.provider_id === connection.provider_id && provider.connection_required)).map(connection => <div className="external-service-card" key={connection.id}>
            <div className="external-service-card-heading"><h3>{connection.name}</h3></div>
            <p className="external-service-muted">{speechProviders.find(provider => provider.provider_id === connection.provider_id)?.name || connection.provider_id} · {{ local: '本机服务', lan: '局域网', cloud: '云端' }[connection.deployment]}</p>
            {connection.base_url && <p className="external-service-muted">{connection.base_url}</p>}
            <div className="external-service-muted">{connection.credential_configured ? '密钥已配置' : '未配置密钥'} · 服务可达性未验证</div>
          </div>)}
          {!speechConnections.some(connection => speechProviders.some(provider => provider.provider_id === connection.provider_id && provider.connection_required)) && <p className="external-service-muted">尚无新的外部语音连接。请在音色实验室创建声音与连接。</p>}
        </>}
        <details className="external-service-muted"><summary>已有配置的导入</summary><p>旧语音配置仍保留在原处。需通过离线导入工具显式导入到新的声音库；此页面不会自动迁移或覆盖旧数据。</p></details>
      </div>
    </section>
    <style>{`
      .external-services { max-width: 1040px; min-width: 0; }
      .external-service-section { border: 1px solid var(--border); border-radius: 12px; background: var(--surface); margin-bottom: 20px; overflow: hidden; }
      .external-service-heading { display: flex; align-items: center; gap: 12px; padding: 18px 20px; background: var(--panel-muted); border-bottom: 1px solid var(--border); }
      .external-service-heading h2 { flex: 1; font-size: 20px; margin: 0; font-weight: 700; }
      .external-service-tag, .external-service-active { color: var(--accent); background: var(--accent-soft); border-radius: 6px; padding: 4px 8px; font-size: 12px; font-weight: 600; }
      .external-service-body { padding: 16px 20px; }
      .external-service-card { padding: 16px; border: 1px solid var(--border); border-radius: 9px; margin-bottom: 12px; min-width: 0; }
      .external-service-card:last-child { margin-bottom: 0; }
      .external-service-card-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
      .external-service-card-heading h3 { font-size: 16px; font-weight: 650; margin: 0; overflow-wrap: anywhere; }
      .external-service-actions { margin-left: auto; display: flex; gap: 8px; }
      .external-service-muted { color: var(--muted); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
      .external-service-editor { border: 0; border-top: 1px solid var(--border); margin: 18px 0 0; padding: 20px 0 0; min-width: 0; }
      .external-service-editor > .external-service-card-heading { justify-content: space-between; margin-bottom: 20px; }
      .external-service-field { display: grid; gap: 6px; font-size: 13px; margin-bottom: 16px; }
      .external-service-field input, .external-service-field select, .external-service-field textarea { width: 100%; min-width: 0; font: inherit; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg); }
      .external-service-button { font: inherit; font-size: 13px; padding: 8px 14px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg); cursor: pointer; }
      .external-service-button:disabled { opacity: .6; cursor: default; }
      .external-service-primary { background: var(--accent); border-color: var(--accent); color: white; }
      .external-service-editor summary { cursor: pointer; font-size: 12px; color: var(--muted); }
      .external-service-notice { padding: 12px 16px; background: var(--panel-muted); border-radius: 8px; margin-bottom: 16px; font-size: 13px; overflow-wrap: anywhere; }
      @media (max-width: 600px) { .external-service-heading { flex-wrap: wrap; padding: 14px; } .external-service-body { padding: 12px; } .external-service-heading h2 { font-size: 18px; } }
    `}</style>
  </div>
}
