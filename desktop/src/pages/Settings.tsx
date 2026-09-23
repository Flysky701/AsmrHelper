import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import { pipelineApi } from '@/api/pipeline'
import type { ConnectionProfile, SettingsUpdate, SettingsView } from '@/api/settings'
import type { PresetItem } from '@/api/types'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useWorkbenchStore } from '@/stores/workbenchStore'

type SettingsTab = 'api' | 'presets' | 'paths'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'api', label: 'API 配置' },
  { id: 'presets', label: '内置预设' },
  { id: 'paths', label: '路径配置' },
]

const PRESET_STAGE_LABELS: Record<string, string> = {
  separation: '人声分离',
  asr: '语音识别',
  translation: '翻译',
  tts: '语音合成',
  mix: '混音',
  export: '导出结果',
}

export default function Settings() {
  const { selectFolder } = useFileSelector()
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState<SettingsTab>('api')
  const [presets, setPresets] = useState<PresetItem[]>([])
  const [settingsLoadError, setSettingsLoadError] = useState('')
  const [presetsLoadError, setPresetsLoadError] = useState('')
  const [presetsLoading, setPresetsLoading] = useState(true)
  const loadGenerationRef = useRef(0)
  const presetGenerationRef = useRef(0)

  // API test state
  const [testResult, setTestResult] = useState<{ success: boolean; msg: string } | null>(null)
  const [testing, setTesting] = useState(false)
  const [externalTts, setExternalTts] = useState({ id: '', name: '', base_url: '', credential: '', credential_configured: false })
  const [llmProfile, setLlmProfile] = useState({ id: '', name: '', credential_configured: false })

  const [models, setModels] = useState<string[]>([])
  const modelGenerationRef = useRef(0)

  // Draft state
  const [draft, setDraft] = useState({
    provider: 'deepseek',
    deepseekKey: '',
    openaiKey: '',
    deepseekBaseUrl: 'https://api.deepseek.com',
    openaiBaseUrl: 'https://api.openai.com/v1',
    deepseekModel: '',
    openaiModel: '',
    outputDir: '',
    vttDir: '',
    modelCacheDir: '',
    tempDir: '',
  })

  useEffect(() => {
    void loadData()
    return () => {
      loadGenerationRef.current += 1
      presetGenerationRef.current += 1
      modelGenerationRef.current += 1
    }
  }, [])

  const hydrateLlm = (profile: ConnectionProfile) => {
    resetModelDiscovery()
    setLlmProfile({ id: profile.id, name: profile.name, credential_configured: profile.credential_configured })
    setDraft(current => ({ ...current, provider: profile.provider,
      deepseekKey: '', openaiKey: '',
      deepseekBaseUrl: profile.provider === 'deepseek' ? profile.base_url : 'https://api.deepseek.com',
      openaiBaseUrl: profile.provider === 'openai' ? profile.base_url : '',
      deepseekModel: profile.provider === 'deepseek' ? profile.model || '' : '',
      openaiModel: profile.provider === 'openai' ? profile.model || '' : '',
    }))
  }

  const hydrateTts = (profile: ConnectionProfile) => {
    setExternalTts({ id: profile.id, name: profile.name, base_url: profile.base_url,
      credential: '', credential_configured: profile.credential_configured })
  }

  const syncWorkbench = (current: SettingsView) => {
    const workbench = useWorkbenchStore.getState()
    const selected = current.providers.default_llm === 'deepseek' ? 'deepseek' : 'openai'
    workbench.updateParam('translateProvider', selected)
    workbench.updateParam('translateModel', current.providers[selected].model)
    if (workbench.params.ttsEngine === 'openai_compatible') {
      workbench.updateParam('ttsVoice', current.external_tts.voice || '')
      if (current.external_tts.api_format === 'mimo_chat') workbench.updateParam('ttsSpeed', 1)
    }
  }

  const loadData = async () => {
    const generation = ++loadGenerationRef.current
    const presetGeneration = ++presetGenerationRef.current
    modelGenerationRef.current += 1
    setTesting(false)
    setModels([])
    setTestResult(null)
    setLoading(true)
    setPresetsLoading(true)
    setMessage('')
    setSettingsLoadError('')
    setPresetsLoadError('')
    try {
      const [settingsResult, presetsResult] = await Promise.allSettled([
        settingsApi.get(),
        pipelineApi.presets(),
      ])
      if (generation !== loadGenerationRef.current) return

      if (settingsResult.status === 'fulfilled') {
        const current = settingsResult.value.settings
        setSettings(current)
        setDraft({
          provider: current.providers.default_llm || 'deepseek',
          deepseekKey: '',
          openaiKey: '',
          deepseekBaseUrl: current.providers.deepseek.base_url || 'https://api.deepseek.com',
          openaiBaseUrl: current.providers.openai.base_url || 'https://api.openai.com/v1',
          deepseekModel: current.providers.deepseek.model || '',
          openaiModel: current.providers.openai.model || '',
          outputDir: current.paths.output_dir || '',
          vttDir: current.paths.vtt_dir || '',
          modelCacheDir: current.paths.model_cache_dir || '',
          tempDir: current.paths.temp_dir || '',
        })
        const profiles = current.connection_profiles
        const llm = profiles.llm.find(item => item.id === profiles.active_llm)
        const tts = profiles.tts.find(item => item.id === profiles.active_tts)
        if (llm) hydrateLlm(llm)
        if (tts) hydrateTts(tts)
      } else {
        setSettings(null)
        setSettingsLoadError(
          `无法读取当前设置：${settingsResult.reason instanceof Error ? settingsResult.reason.message : String(settingsResult.reason)}`,
        )
      }

      if (presetGeneration === presetGenerationRef.current) {
        if (presetsResult.status === 'fulfilled') {
          setPresets(presetsResult.value.presets || [])
        } else {
          setPresets([])
          setPresetsLoadError(
            `无法加载内置预设：${presetsResult.reason instanceof Error ? presetsResult.reason.message : String(presetsResult.reason)}`,
          )
        }
      }
    } finally {
      if (generation === loadGenerationRef.current) setLoading(false)
      if (presetGeneration === presetGenerationRef.current) setPresetsLoading(false)
    }
  }

  const reloadPresets = async () => {
    const generation = ++presetGenerationRef.current
    setPresetsLoading(true)
    setPresetsLoadError('')
    try {
      const result = await pipelineApi.presets()
      if (generation !== presetGenerationRef.current) return
      setPresets(result.presets || [])
    } catch (error) {
      if (generation !== presetGenerationRef.current) return
      setPresetsLoadError(`无法加载内置预设：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      if (generation === presetGenerationRef.current) setPresetsLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const updates: SettingsUpdate = {
        paths: {
          output_dir: draft.outputDir,
          vtt_dir: draft.vttDir,
          model_cache_dir: draft.modelCacheDir,
          temp_dir: draft.tempDir,
        },
      }
      const result = await settingsApi.validate(updates)
      if (!result.valid) {
        setMessage(`验证失败: ${result.errors.join('; ')}`)
        return
      }
      await settingsApi.update(updates)
      setMessage('路径已保存')
    } catch (err) {
      setMessage(`保存失败: ${err}`)
    } finally {
      setSaving(false)
    }
  }

  const provider = draft.provider === 'deepseek' ? 'deepseek' : 'openai'
  const providerLabel = provider === 'deepseek' ? 'DeepSeek' : 'OpenAI / 兼容接口'
  const keyField = provider === 'deepseek' ? 'deepseekKey' : 'openaiKey'
  const urlField = provider === 'deepseek' ? 'deepseekBaseUrl' : 'openaiBaseUrl'
  const modelField = provider === 'deepseek' ? 'deepseekModel' : 'openaiModel'
  const selectedModel = draft[modelField]

  const resetModelDiscovery = () => {
    modelGenerationRef.current += 1
    setTesting(false)
    setModels([])
    setTestResult(null)
  }

  const llmCandidate = (): SettingsUpdate => ({ connection_profile: {
    kind: 'llm', ...(llmProfile.id ? { id: llmProfile.id } : {}),
    name: llmProfile.name.trim() || '未命名翻译配置', provider,
    base_url: draft[urlField], model: selectedModel,
    ...(draft[keyField] ? { credential: draft[keyField] } : {}),
  } })

  const saveProfile = async (kind: 'llm' | 'tts') => {
    if (!(kind === 'llm' ? llmProfile.name : externalTts.name).trim()) {
      setMessage('保存失败：请填写配置名称')
      return
    }
    if (kind === 'llm' && !selectedModel.trim()) {
      setMessage('保存失败：请获取并选择模型，或按服务商文档手动填写模型')
      return
    }
    setSaving(true)
    setMessage('')
    resetModelDiscovery()
    try {
      const updates: SettingsUpdate = kind === 'llm' ? llmCandidate() : { connection_profile: {
        kind: 'tts', ...(externalTts.id ? { id: externalTts.id } : {}),
        name: externalTts.name.trim(), provider: 'openai_compatible', base_url: externalTts.base_url,
        ...(externalTts.credential ? { credential: externalTts.credential } : {}),
      } }
      const result = await settingsApi.update(updates)
      setSettings(result.settings)
      const profiles = result.settings.connection_profiles
      const profile = profiles[kind].find(item => item.id === (kind === 'llm' ? profiles.active_llm : profiles.active_tts))
      if (profile) kind === 'llm' ? hydrateLlm(profile) : hydrateTts(profile)
      syncWorkbench(result.settings)
      setMessage('配置已保存并启用')
    } catch (error) {
      setMessage(`保存失败：${error instanceof Error ? error.message : String(error)}`)
    } finally { setSaving(false) }
  }

  const selectProfile = (kind: 'llm' | 'tts', id: string) => {
    const profile = settings?.connection_profiles[kind].find(item => item.id === id)
    if (!profile) return
    if (kind === 'llm') hydrateLlm(profile)
    else hydrateTts(profile)
    setMessage('已载入配置，保存并启用后用于新任务')
  }

  const handleDiscoverModels = async () => {
    const generation = ++modelGenerationRef.current
    setTesting(true)
    setTestResult(null)
    setModels([])
    try {
      const candidate = llmCandidate()
      const result = await settingsApi.listModels(provider, candidate)
      if (generation !== modelGenerationRef.current) return
      const available = [...new Set(result.models)]
      setModels(available)
      setTestResult({
        success: available.length > 0,
        msg: available.length > 0
          ? `已获取 ${available.length} 个模型，请选择用于翻译的模型。`
          : '服务未返回可选模型。可重试，或根据服务商文档手动填写。',
      })
    } catch (error) {
      if (generation !== modelGenerationRef.current) return
      setTestResult({ success: false, msg: `获取模型失败：${error instanceof Error ? error.message : String(error)}。可检查连接信息后重试，或根据服务商文档手动填写。` })
    } finally {
      if (generation === modelGenerationRef.current) setTesting(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--muted)' }}>
        加载设置中...
      </div>
    )
  }

  if (!settings) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%',
        padding: '24px', background: 'var(--bg)',
      }}>
        <div role="alert" style={{
          width: 'min(460px, 100%)', padding: '24px', borderRadius: '10px',
          border: '1px solid var(--border)', background: 'var(--surface)', textAlign: 'center',
        }}>
          <h2 style={{
            margin: '0 0 8px', fontFamily: 'var(--font-display)', fontSize: '17px', fontWeight: 600,
          }}>
            设置暂时无法加载
          </h2>
          <p style={{ margin: '0 0 18px', color: 'var(--muted)', fontSize: '13px', lineHeight: 1.6 }}>
            {settingsLoadError || '未能读取当前设置。为避免覆盖已有配置，编辑和保存已暂停。'}
          </p>
          <button onClick={() => void loadData()} style={{
            fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '8px 16px',
            borderRadius: '6px', border: '1px solid var(--accent)', background: 'var(--accent)',
            color: 'white', cursor: 'pointer',
          }}>
            重新加载
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="settings-page" style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%', overflow: 'hidden' }}>
      {/* Action bar */}
      <div className="settings-action-bar" style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: '12px',
      }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '22px', fontWeight: 700, letterSpacing: '-0.02em', marginRight: '16px' }}>
          设置
        </h1>
        <div className="settings-action-spacer" style={{ flex: 1 }} />
        {activeTab === 'presets' ? (
          <span style={{
            fontSize: '12px', color: 'var(--muted)', padding: '6px 10px',
            borderRadius: '999px', background: 'var(--panel-muted)',
          }}>
            内置流程 · 无需保存
          </span>
        ) : activeTab === 'paths' ? (
          <>
            <button onClick={handleSave} disabled={saving} style={{
              fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
              borderRadius: '6px', border: '1px solid var(--accent)', background: 'var(--accent)',
              color: 'white', cursor: 'pointer', opacity: saving ? 0.6 : 1,
            }}>
              {saving ? '保存中...' : '保存'}
            </button>
          </>
        ) : null}
      </div>

      {/* Content: nav + panel */}
      <div className="settings-layout" style={{ display: 'grid', gridTemplateColumns: '180px 1fr', overflow: 'hidden' }}>

        {/* Settings nav */}
        <nav className="settings-nav" style={{ background: 'var(--surface)', borderRight: '1px solid var(--border)', padding: '16px 0' }}>
          {TABS.map(tab => (
            <div
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '8px 20px', fontSize: '13px', color: activeTab === tab.id ? 'var(--accent)' : 'var(--muted)',
                cursor: 'pointer', borderLeft: `3px solid ${activeTab === tab.id ? 'var(--accent)' : 'transparent'}`,
                fontWeight: activeTab === tab.id ? 500 : 400,
                background: activeTab === tab.id ? 'oklch(98% 0.005 255)' : 'none',
              }}
            >
              {tab.label}
            </div>
          ))}
        </nav>

        {/* Settings panel */}
        <div className="settings-panel" style={{ padding: '28px 32px', overflowY: 'auto', maxWidth: '680px' }}>

          {/* Status message */}
          {message && (
            <div className="settings-message" role="status" style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 12px',
              borderRadius: '6px', fontSize: '12px', marginBottom: '16px',
              background: message.includes('失败') ? 'oklch(95% 0.03 25)' : 'oklch(95% 0.03 145)',
              color: message.includes('失败') ? 'oklch(40% 0.12 25)' : 'oklch(35% 0.1 145)',
            }}>
              <span style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: message.includes('失败') ? 'oklch(55% 0.18 25)' : 'oklch(60% 0.16 145)',
              }} />
              {message}
            </div>
          )}

          {/* Panel: API 配置 */}
          {activeTab === 'api' && (
            <fieldset disabled={saving} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
              <details className="settings-service-section" open>
                <summary className="settings-service-heading">
                  <span className="settings-service-tag">LLM</span>
                  <h2 className="settings-section-title">翻译服务</h2>
                  <span className="settings-service-toggle" aria-hidden="true" />
                </summary>
                <div className="settings-service-body">
                <label className="settings-field">
                  已保存的配置
                  <select value={llmProfile.id} disabled={saving} onChange={event => void selectProfile('llm', event.target.value)}>
                    {!llmProfile.id && <option value="" disabled>新建配置</option>}
                    {settings.connection_profiles.llm.map(profile => <option key={profile.id} value={profile.id}>{profile.name}{profile.id === settings.connection_profiles.active_llm ? '（已启用）' : ''}</option>)}
                  </select>
                </label>
                <button className="settings-secondary-button" disabled={saving} onClick={() => {
                  hydrateLlm({ id: '', name: '', provider: 'deepseek', base_url: 'https://api.deepseek.com', model: '', credential_configured: false })
                  setMessage('填写新配置后保存并启用')
                }}>新建翻译配置</button>
                <label className="settings-field" style={{ marginTop: 16 }}>
                  配置名称
                  <input value={llmProfile.name} maxLength={100} onChange={event => setLlmProfile({ ...llmProfile, name: event.target.value })} placeholder="例如：日常翻译" />
                </label>
                <label className="settings-field">
                  服务提供商
                  <select value={provider} disabled={!!llmProfile.id || saving} onChange={event => {
                    resetModelDiscovery()
                    setDraft({ ...draft, provider: event.target.value, deepseekKey: '', openaiKey: '',
                      deepseekBaseUrl: 'https://api.deepseek.com', openaiBaseUrl: '', deepseekModel: '', openaiModel: '' })
                  }}>
                    <option value="deepseek">DeepSeek</option>
                    <option value="openai">OpenAI / 兼容接口</option>
                  </select>
                </label>
                <label className="settings-field">
                  {providerLabel} API 地址
                  <input value={draft[urlField]} onChange={event => {
                    resetModelDiscovery()
                    setDraft({ ...draft, [urlField]: event.target.value })
                  }} />
                </label>
                <label className="settings-field">
                  API 密钥
                  <input type="password" autoComplete="off" value={draft[keyField]} onChange={event => {
                    resetModelDiscovery()
                    setDraft({ ...draft, [keyField]: event.target.value })
                  }} placeholder={llmProfile.credential_configured ? '已配置；留空保持此配置的密钥' : '输入 API 密钥'} />
                </label>
                <button className="settings-secondary-button" onClick={() => void handleDiscoverModels()} disabled={testing || saving}>
                  {testing ? '正在获取模型...' : '检测连接并获取模型'}
                </button>
                {testResult && (
                  <p role="status" style={{ fontSize: 12, lineHeight: 1.6, color: testResult.success ? 'var(--muted)' : 'oklch(40% 0.12 25)' }}>
                    {testResult.msg}
                  </p>
                )}
                <label className="settings-field" style={{ marginTop: 16 }}>
                  翻译模型
                  <select value={selectedModel} disabled={!selectedModel && models.length === 0} onChange={event => setDraft({ ...draft, [modelField]: event.target.value })}>
                    <option value="">{models.length > 0 ? '选择模型' : '获取模型后选择'}</option>
                    {selectedModel && !models.includes(selectedModel) && (
                      <option value={selectedModel}>{selectedModel}（当前配置，未核验）</option>
                    )}
                    {models.map(model => <option key={model} value={model}>{model}</option>)}
                  </select>
                </label>
                <details key={`${llmProfile.id}-${provider}`} style={{ fontSize: 12, color: 'var(--muted)' }}>
                  <summary style={{ cursor: 'pointer' }}>手动填写模型</summary>
                  <label className="settings-field" style={{ marginTop: 12 }}>
                    服务商文档中的模型 ID
                    <input value={selectedModel} onChange={event => setDraft({ ...draft, [modelField]: event.target.value })} placeholder="填写文档中支持翻译的模型 ID" />
                  </label>
                </details>
                <button className="settings-secondary-button" style={{ marginTop: 16 }} disabled={saving} onClick={() => void saveProfile('llm')}>
                  保存并启用翻译配置
                </button>
                </div>
              </details>
              <details className="settings-service-section">
                <summary className="settings-service-heading">
                  <span className="settings-service-tag">TTS</span>
                  <h2 className="settings-section-title">外部语音合成</h2>
                  <span className="settings-service-toggle" aria-hidden="true" />
                </summary>
                <div className="settings-service-body">
                <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>OpenAI 兼容语音接口</p>
                <label className="settings-field">
                  已保存的配置
                  <select value={externalTts.id} disabled={saving} onChange={event => void selectProfile('tts', event.target.value)}>
                    {!externalTts.id && <option value="" disabled>新建配置</option>}
                    {settings.connection_profiles.tts.map(profile => <option key={profile.id} value={profile.id}>{profile.name}{profile.id === settings.connection_profiles.active_tts ? '（已启用）' : ''}</option>)}
                  </select>
                </label>
                <button className="settings-secondary-button" disabled={saving} onClick={() => {
                  hydrateTts({ id: '', name: '', provider: 'openai_compatible', base_url: '', credential_configured: false })
                  setMessage('填写新配置后保存并启用')
                }}>新建语音配置</button>
                <label className="settings-field" style={{ marginTop: 16 }}>
                  配置名称
                  <input value={externalTts.name} maxLength={100} onChange={event => setExternalTts({ ...externalTts, name: event.target.value })} placeholder="例如：旁白语音" />
                </label>
                {([
                  { key: 'base_url', label: 'API 地址', placeholder: '填写服务商提供的 API 基础地址' },
                  { key: 'credential', label: 'API 密钥', placeholder: externalTts.credential_configured ? '已配置；留空保持此配置的密钥' : '输入 API 密钥' },
                ] as const).map(field => (
                  <label key={field.key} className="settings-field">
                    {field.label}
                    <input
                      type={field.key === 'credential' ? 'password' : 'text'}
                      autoComplete={field.key === 'credential' ? 'off' : undefined}
                      value={externalTts[field.key]}
                      onChange={event => setExternalTts({ ...externalTts, [field.key]: event.target.value })}
                      placeholder={field.placeholder}
                    />
                  </label>
                ))}
                <p style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
                  目前仅配置连接信息；模型与音色选项待依据服务商文档或接口探测接入。
                </p>
                <button className="settings-secondary-button" disabled={saving} onClick={() => void saveProfile('tts')}>
                  保存并启用语音配置
                </button>
                </div>
              </details>
            </fieldset>
          )}

          {/* Panel: 内置预设 */}
          {activeTab === 'presets' && (
            <div>
              <div style={{ marginBottom: '32px' }}>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '16px', fontWeight: 600, letterSpacing: '-0.02em', marginBottom: '4px' }}>
                  内置管道预设
                </h2>
                <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '16px' }}>
                  当前版本只展示已经接入执行链路的流程。请在工作台中选择预设并创建任务。
                </div>

                <div style={{
                  display: 'flex', alignItems: 'flex-start', gap: '10px', marginBottom: '16px',
                  padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--border)',
                  background: 'var(--panel-muted)',
                }}>
                  <span aria-hidden="true" style={{
                    width: '18px', height: '18px', borderRadius: '50%', flex: '0 0 auto',
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    background: 'var(--accent-soft)', color: 'var(--accent)', fontSize: '12px', fontWeight: 700,
                  }}>
                    i
                  </span>
                  <div style={{ fontSize: '12px', lineHeight: 1.6, color: 'var(--muted)' }}>
                    <strong style={{ display: 'block', color: 'var(--fg)', fontWeight: 600 }}>只读说明</strong>
                    这些流程由应用内置并统一维护，本页用于核对处理范围，不提供新建、编辑或删除操作。
                  </div>
                </div>

                {presetsLoadError && (
                  <div role="alert" style={{
                    display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px',
                    padding: '12px 14px', borderRadius: '8px', border: '1px solid oklch(82% 0.06 25)',
                    background: 'oklch(96% 0.025 25)', color: 'oklch(40% 0.12 25)',
                  }}>
                    <div style={{ flex: 1, minWidth: 0, fontSize: '12px', lineHeight: 1.55, overflowWrap: 'anywhere' }}>
                      <strong style={{ display: 'block', marginBottom: '2px', fontWeight: 600 }}>预设加载失败</strong>
                      {presetsLoadError}
                    </div>
                    <button onClick={() => void reloadPresets()} disabled={presetsLoading} style={{
                      flex: '0 0 auto', fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
                      padding: '7px 12px', borderRadius: '6px', border: '1px solid var(--border)',
                      background: 'var(--surface)', color: 'var(--fg)', cursor: presetsLoading ? 'default' : 'pointer',
                      opacity: presetsLoading ? 0.6 : 1,
                    }}>
                      {presetsLoading ? '重试中...' : '重新加载'}
                    </button>
                  </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {presets.map(preset => (
                    <div key={preset.id} style={{
                      border: '1px solid var(--border)', borderRadius: '10px', background: 'var(--surface)',
                      padding: '16px',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, flex: 1 }}>{preset.label}</span>
                        <span style={{
                          fontSize: '11px', color: 'var(--muted)', padding: '3px 8px',
                          borderRadius: '999px', border: '1px solid var(--border)', whiteSpace: 'nowrap',
                        }}>
                          内置 · 只读
                        </span>
                      </div>
                      <p style={{ margin: '0 0 14px', color: 'var(--muted)', fontSize: '12px', lineHeight: 1.65 }}>
                        {preset.description}
                      </p>
                      <div style={{ fontSize: '11px', color: 'var(--muted)', marginBottom: '7px' }}>实际执行阶段</div>
                      <div className="settings-preset-stages" style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        {preset.stages.map((stage, index) => (
                          <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            {index > 0 && <span aria-hidden="true" style={{ color: 'var(--border-strong)', fontSize: '12px' }}>→</span>}
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: '5px',
                              padding: '5px 8px', borderRadius: '6px', background: 'var(--accent-soft)',
                              color: 'var(--accent)', fontSize: '12px', fontWeight: 500,
                            }}>
                              <span style={{ fontSize: '10px', opacity: 0.72 }}>{index + 1}</span>
                              {PRESET_STAGE_LABELS[stage] ?? '其他处理'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}

                  {presetsLoading && presets.length === 0 && (
                    <div style={{ fontSize: '13px', color: 'var(--muted)', padding: '16px', textAlign: 'center' }}>
                      正在加载内置预设...
                    </div>
                  )}

                  {!presetsLoading && !presetsLoadError && presets.length === 0 && (
                    <div style={{ fontSize: '13px', color: 'var(--muted)', padding: '16px', textAlign: 'center' }}>
                      当前没有可用的内置预设。
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Panel: 路径配置 */}
          {activeTab === 'paths' && (
            <div>
              <div style={{ marginBottom: '32px' }}>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '16px', fontWeight: 600, letterSpacing: '-0.02em', marginBottom: '4px' }}>
                  路径配置
                </h2>
                <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '16px' }}>
                  输出目录和模型缓存位置。留空使用默认值。
                </div>

                {[
                  { key: 'outputDir' as const, label: '输出目录', placeholder: '默认: ./output', hint: '处理结果文件的存放位置' },
                  { key: 'vttDir' as const, label: 'VTT 字幕目录', placeholder: '默认: 与音频同目录', hint: '字幕文件的读取和保存位置' },
                  { key: 'modelCacheDir' as const, label: '模型缓存目录', placeholder: '默认: ./models', hint: '下载的模型文件存储位置，可能需要较大空间' },
                  { key: 'tempDir' as const, label: '临时文件目录', placeholder: '默认: 系统临时目录', hint: '处理过程中的临时文件，任务完成后自动清理' },
                ].map(field => (
                  <div key={field.key} style={{ marginBottom: '16px' }}>
                    <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>{field.label}</label>
                    <div className="settings-path-row" style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        value={draft[field.key]}
                        onChange={e => setDraft({ ...draft, [field.key]: e.target.value })}
                        placeholder={field.placeholder}
                        style={{
                          flex: 1, fontFamily: 'var(--font-mono)', fontSize: '12px', padding: '8px 10px',
                          borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                          color: 'var(--fg)',
                        }}
                      />
                      <button onClick={async () => {
                        const selected = await selectFolder()
                        if (selected) {
                          setDraft((current) => ({ ...current, [field.key]: selected }))
                        }
                      }} style={{
                        fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
                        borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                        color: 'var(--fg)', cursor: 'pointer', flexShrink: 0,
                      }}>
                        浏览
                      </button>
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '3px' }}>{field.hint}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .settings-service-section {
          border: 1px solid var(--border);
          border-radius: 10px;
          background: var(--surface);
          margin-bottom: 16px;
        }

        .settings-service-heading {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 18px 20px;
          cursor: pointer;
          list-style: none;
          border-radius: 10px;
          background: var(--panel-muted);
        }

        .settings-service-heading::-webkit-details-marker { display: none; }
        .settings-service-heading:hover { background: var(--accent-soft); }
        .settings-service-section[open] > .settings-service-heading {
          border-bottom: 1px solid var(--border);
          border-radius: 10px 10px 0 0;
        }

        .settings-section-title {
          margin: 0;
          font-family: var(--font-display);
          font-size: 20px;
          font-weight: 700;
          line-height: 1.4;
          color: var(--fg);
        }

        .settings-service-tag {
          flex-shrink: 0;
          padding: 4px 7px;
          border-radius: 5px;
          background: var(--accent-soft);
          color: var(--accent);
          font-size: 12px;
          font-weight: 700;
        }

        .settings-service-toggle {
          margin-left: auto;
          font-size: 12px;
          color: var(--muted);
          flex-shrink: 0;
        }
        .settings-service-toggle::before { content: '展开 ＋'; }
        .settings-service-section[open] > summary .settings-service-toggle::before { content: '收起 −'; }
        .settings-service-body { padding: 20px; }

        @media (max-width: 600px) {
          .settings-service-heading { gap: 8px; padding: 14px 12px; }
          .settings-section-title { font-size: 18px; }
          .settings-service-body { padding: 16px 12px; }
        }

        .settings-field {
          display: grid;
          gap: 6px;
          font-size: 12px;
          margin-bottom: 16px;
        }

        .settings-field input,
        .settings-field select {
          width: 100%;
          min-width: 0;
          font-family: var(--font-body);
          font-size: 13px;
          padding: 8px 10px;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--fg);
        }

        .settings-secondary-button {
          font-family: var(--font-body);
          font-size: 13px;
          padding: 8px 14px;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--surface);
          color: var(--fg);
          cursor: pointer;
        }

        .settings-secondary-button:disabled {
          opacity: 0.6;
          cursor: wait;
        }

        .settings-page,
        .settings-layout,
        .settings-panel,
        .settings-provider-row > input,
        .settings-path-row > input {
          min-width: 0;
        }

        .settings-message,
        .settings-path-row,
        .settings-panel input {
          overflow-wrap: anywhere;
          word-break: break-word;
        }

        .settings-message > span:first-child {
          flex: 0 0 auto;
        }

        @media (max-width: 1100px) {
          .settings-layout {
            grid-template-columns: minmax(0, 1fr) !important;
            grid-template-rows: auto minmax(0, 1fr);
          }

          .settings-nav {
            display: flex;
            overflow-x: auto;
            padding: 0 12px !important;
            border-right: 0 !important;
            border-bottom: 1px solid var(--border);
          }

          .settings-nav > div {
            flex: 0 0 auto;
            padding: 11px 16px !important;
          }

          .settings-panel {
            width: 100%;
            max-width: none !important;
          }
        }

        @media (max-width: 760px) {
          .settings-action-bar {
            flex-wrap: wrap;
            padding: 12px 16px !important;
          }

          .settings-action-bar > h1 {
            flex: 1 0 100%;
            margin-right: 0 !important;
          }

          .settings-action-spacer {
            display: none;
          }

          .settings-action-bar > button {
            flex: 1 1 0;
            justify-content: center;
          }

          .settings-panel {
            padding: 20px 16px !important;
          }

          .settings-provider-row,
          .settings-path-row {
            align-items: stretch !important;
            flex-direction: column;
          }

          .settings-provider-row > button,
          .settings-path-row > button {
            width: 100%;
          }

          .settings-preset-stages {
            align-items: flex-start !important;
          }
        }
      `}</style>
    </div>
  )
}
