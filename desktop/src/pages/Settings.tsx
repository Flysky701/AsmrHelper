import { useEffect, useState } from 'react'
import { settingsApi } from '@/api/settings'
import { pipelineApi } from '@/api/pipeline'
import type { SettingsResponse } from '@/api/settings'

type SettingsTab = 'api' | 'presets' | 'paths'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'api', label: 'API 配置' },
  { id: 'presets', label: '预设管理' },
  { id: 'paths', label: '路径配置' },
]

export default function Settings() {
  const [_settings, setSettings] = useState<SettingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState<SettingsTab>('api')
  const [presets, setPresets] = useState<Array<{ id: string; label: string }>>([])

  // API test state
  const [testResult, setTestResult] = useState<{ success: boolean; msg: string } | null>(null)
  const [testing, setTesting] = useState(false)

  // Validation state
  const [validation, setValidation] = useState<{ valid: boolean; errors: string[] } | null>(null)

  // Draft state
  const [draft, setDraft] = useState({
    provider: 'deepseek',
    deepseekKey: '',
    openaiKey: '',
    deepseekBaseUrl: 'https://api.deepseek.com',
    openaiBaseUrl: 'https://api.openai.com/v1',
    outputDir: '',
    vttDir: '',
    modelCacheDir: '',
    tempDir: '',
  })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [settingsData, presetsData] = await Promise.all([
        settingsApi.get().catch(() => null),
        pipelineApi.presets().catch(() => ({ presets: [] })),
      ])
      if (settingsData) {
        setSettings(settingsData)
        setDraft({
          provider: settingsData.api.provider || 'deepseek',
          deepseekKey: settingsData.api.deepseek_api_key || '',
          openaiKey: settingsData.api.openai_api_key || '',
          deepseekBaseUrl: settingsData.api.deepseek_base_url || 'https://api.deepseek.com',
          openaiBaseUrl: settingsData.api.openai_base_url || 'https://api.openai.com/v1',
          outputDir: settingsData.paths.output_dir || '',
          vttDir: settingsData.paths.vtt_dir || '',
          modelCacheDir: settingsData.paths.model_cache_dir || '',
          tempDir: settingsData.paths.temp_dir || '',
        })
      }
      setPresets(presetsData.presets || [])
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const updates: Partial<SettingsResponse> = {
        api: {
          provider: draft.provider,
          deepseek_api_key: draft.deepseekKey,
          openai_api_key: draft.openaiKey,
          deepseek_base_url: draft.deepseekBaseUrl,
          openai_base_url: draft.openaiBaseUrl,
        },
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
        setValidation({ valid: false, errors: result.errors })
        return
      }
      await settingsApi.update(updates)
      setValidation({ valid: true, errors: [] })
      setMessage('设置已保存')
      loadData()
    } catch (err) {
      setMessage(`保存失败: ${err}`)
    } finally {
      setSaving(false)
    }
  }

  const handleTestProvider = async (provider: string) => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await settingsApi.testProvider(provider)
      setTestResult({ success: result.success, msg: result.success ? '连接成功' : result.errors.join('; ') })
    } catch (err) {
      setTestResult({ success: false, msg: `测试失败: ${err}` })
    } finally {
      setTesting(false)
    }
  }

  const handleValidate = async () => {
    try {
      const result = await settingsApi.validate()
      setValidation({ valid: result.valid, errors: result.errors })
    } catch {
      setValidation({ valid: false, errors: ['验证请求失败'] })
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--muted)' }}>
        加载设置中...
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%', overflow: 'hidden' }}>
      {/* Action bar */}
      <div style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: '12px',
      }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '15px', fontWeight: 600, letterSpacing: '-0.02em', marginRight: '16px' }}>
          设置
        </h1>
        <div style={{ flex: 1 }} />
        <button onClick={handleValidate} style={{
          fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
          borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
          color: 'var(--fg)', cursor: 'pointer',
        }}>
          验证配置
        </button>
        <button onClick={handleSave} disabled={saving} style={{
          fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
          borderRadius: '6px', border: '1px solid var(--accent)', background: 'var(--accent)',
          color: 'white', cursor: 'pointer', opacity: saving ? 0.6 : 1,
        }}>
          {saving ? '保存中...' : '保存'}
        </button>
      </div>

      {/* Content: nav + panel */}
      <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', overflow: 'hidden' }}>

        {/* Settings nav */}
        <nav style={{ background: 'var(--surface)', borderRight: '1px solid var(--border)', padding: '16px 0' }}>
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
        <div style={{ padding: '28px 32px', overflowY: 'auto', maxWidth: '680px' }}>

          {/* Status message */}
          {message && (
            <div style={{
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

          {/* Validation bar */}
          {validation && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px',
              borderRadius: '6px', fontSize: '12px', marginBottom: '16px',
              background: validation.valid ? 'oklch(95% 0.03 145)' : 'oklch(95% 0.03 25)',
              color: validation.valid ? 'oklch(35% 0.1 145)' : 'oklch(40% 0.12 25)',
            }}>
              <span style={{
                width: '6px', height: '6px', borderRadius: '50%',
                background: validation.valid ? 'oklch(60% 0.16 145)' : 'oklch(55% 0.18 25)',
              }} />
              {validation.valid ? '配置验证通过 · 所有必填项已配置' : `验证失败 · ${validation.errors.join('; ')}`}
            </div>
          )}

          {/* Panel: API 配置 */}
          {activeTab === 'api' && (
            <div>
              <div style={{ marginBottom: '32px' }}>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '16px', fontWeight: 600, letterSpacing: '-0.02em', marginBottom: '4px' }}>
                  翻译服务
                </h2>
                <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '16px' }}>
                  LLM 翻译服务的 API 密钥和端点。环境变量优先级高于此处配置。
                </div>

                {/* Provider select */}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>服务提供商</label>
                  <select
                    value={draft.provider}
                    onChange={e => setDraft({ ...draft, provider: e.target.value })}
                    style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px', padding: '8px 10px',
                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                      color: 'var(--fg)', width: '100%',
                    }}
                  >
                    <option value="deepseek">DeepSeek</option>
                    <option value="openai">OpenAI</option>
                  </select>
                </div>

                {/* DeepSeek API Key */}
                <div style={{ marginBottom: '16px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>DeepSeek API Key</label>
                      <input
                        type="password"
                        value={draft.deepseekKey}
                        onChange={e => setDraft({ ...draft, deepseekKey: e.target.value })}
                        placeholder="sk-..."
                        style={{
                          fontFamily: 'var(--font-mono)', fontSize: '13px', padding: '8px 10px',
                          borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                          color: 'var(--fg)', width: '100%', letterSpacing: '0.05em',
                        }}
                      />
                      <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '3px' }}>环境变量: DEEPSEEK_API_KEY 优先</div>
                    </div>
                    <button onClick={() => handleTestProvider('deepseek')} disabled={testing} style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                      color: 'var(--fg)', cursor: 'pointer', whiteSpace: 'nowrap', height: '36px',
                    }}>
                      测试连通
                    </button>
                  </div>
                </div>

                {/* DeepSeek Base URL */}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>DeepSeek Base URL</label>
                  <input
                    type="text"
                    value={draft.deepseekBaseUrl}
                    onChange={e => setDraft({ ...draft, deepseekBaseUrl: e.target.value })}
                    placeholder="https://api.deepseek.com"
                    style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px', padding: '8px 10px',
                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                      color: 'var(--fg)', width: '100%',
                    }}
                  />
                </div>

                {/* OpenAI API Key */}
                <div style={{ marginBottom: '16px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>OpenAI API Key</label>
                      <input
                        type="password"
                        value={draft.openaiKey}
                        onChange={e => setDraft({ ...draft, openaiKey: e.target.value })}
                        placeholder="sk-..."
                        style={{
                          fontFamily: 'var(--font-mono)', fontSize: '13px', padding: '8px 10px',
                          borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                          color: 'var(--fg)', width: '100%', letterSpacing: '0.05em',
                        }}
                      />
                      <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '3px' }}>环境变量: OPENAI_API_KEY 优先</div>
                    </div>
                    <button onClick={() => handleTestProvider('openai')} disabled={testing} style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                      color: 'var(--fg)', cursor: 'pointer', whiteSpace: 'nowrap', height: '36px',
                    }}>
                      测试连通
                    </button>
                  </div>
                </div>

                {/* OpenAI Base URL */}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>OpenAI Base URL</label>
                  <input
                    type="text"
                    value={draft.openaiBaseUrl}
                    onChange={e => setDraft({ ...draft, openaiBaseUrl: e.target.value })}
                    placeholder="https://api.openai.com/v1"
                    style={{
                      fontFamily: 'var(--font-body)', fontSize: '13px', padding: '8px 10px',
                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                      color: 'var(--fg)', width: '100%',
                    }}
                  />
                </div>

                {/* Test result */}
                {testResult && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 12px',
                    borderRadius: '6px', fontSize: '12px', marginTop: '8px',
                    background: testResult.success ? 'oklch(95% 0.03 145)' : 'oklch(95% 0.03 25)',
                    color: testResult.success ? 'oklch(35% 0.1 145)' : 'oklch(40% 0.12 25)',
                  }}>
                    <span style={{
                      width: '6px', height: '6px', borderRadius: '50%',
                      background: testResult.success ? 'oklch(60% 0.16 145)' : 'oklch(55% 0.18 25)',
                    }} />
                    {testResult.msg}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Panel: 预设管理 */}
          {activeTab === 'presets' && (
            <div>
              <div style={{ marginBottom: '32px' }}>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '16px', fontWeight: 600, letterSpacing: '-0.02em', marginBottom: '4px' }}>
                  管道预设
                </h2>
                <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '16px' }}>
                  定义处理管道的阶段组合。预设在工作台中选择，决定任务执行哪些步骤。
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {presets.map(preset => (
                    <div key={preset.id} style={{
                      border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface)', overflow: 'hidden',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', padding: '14px 16px', gap: '12px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, flex: 1 }}>{preset.label}</span>
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button style={{
                            fontFamily: 'var(--font-body)', fontSize: '12px', padding: '5px 10px',
                            borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                            color: 'var(--fg)', cursor: 'pointer',
                          }}>
                            编辑
                          </button>
                          <button style={{
                            fontFamily: 'var(--font-body)', fontSize: '12px', padding: '5px 10px',
                            borderRadius: '6px', border: '1px solid oklch(85% 0.06 25)', background: 'var(--surface)',
                            color: 'oklch(55% 0.18 25)', cursor: 'pointer',
                          }}>
                            删除
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}

                  {presets.length === 0 && (
                    <div style={{ fontSize: '13px', color: 'var(--muted)', padding: '16px', textAlign: 'center' }}>
                      暂无预设，请先创建
                    </div>
                  )}
                </div>

                <button style={{
                  marginTop: '16px', fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500,
                  padding: '7px 14px', borderRadius: '6px', border: '1px solid var(--border)',
                  background: 'var(--surface)', color: 'var(--fg)', cursor: 'pointer',
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                }}>
                  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M7 2v10M2 7h10" /></svg>
                  新建预设
                </button>
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
                    <div style={{ display: 'flex', gap: '8px' }}>
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
                      <button style={{
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
    </div>
  )
}
