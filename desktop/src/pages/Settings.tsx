import { useEffect, useState } from 'react'
import { settingsApi } from '@/api/settings'
import { pipelineApi } from '@/api/pipeline'
import type { SettingsUpdate, SettingsView } from '@/api/settings'
import type { PresetItem } from '@/api/types'
import { useFileSelector } from '@/hooks/useFileSelector'

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
    setMessage('')
    try {
      const [settingsData, presetsData] = await Promise.all([
        settingsApi.get(),
        pipelineApi.presets(),
      ])
      const current = settingsData.settings
      setSettings(current)
      setDraft({
        provider: current.providers.default_llm || 'deepseek',
        deepseekKey: '',
        openaiKey: '',
        deepseekBaseUrl: current.providers.deepseek.base_url || 'https://api.deepseek.com',
        openaiBaseUrl: current.providers.openai.base_url || 'https://api.openai.com/v1',
        outputDir: current.paths.output_dir || '',
        vttDir: current.paths.vtt_dir || '',
        modelCacheDir: current.paths.model_cache_dir || '',
        tempDir: current.paths.temp_dir || '',
      })
      setPresets(presetsData.presets || [])
    } catch (error) {
      setMessage(`加载设置失败: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const updates: SettingsUpdate = {
        providers: {
          default_llm: draft.provider,
          deepseek: {
            base_url: draft.deepseekBaseUrl,
            ...(draft.deepseekKey ? { credential: draft.deepseekKey } : {}),
          },
          openai: {
            base_url: draft.openaiBaseUrl,
            ...(draft.openaiKey ? { credential: draft.openaiKey } : {}),
          },
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
      const providerUpdate: SettingsUpdate = provider === 'deepseek'
        ? {
            providers: {
              deepseek: {
                base_url: draft.deepseekBaseUrl,
                ...(draft.deepseekKey ? { credential: draft.deepseekKey } : {}),
              },
            },
          }
        : {
            providers: {
              openai: {
                base_url: draft.openaiBaseUrl,
                ...(draft.openaiKey ? { credential: draft.openaiKey } : {}),
              },
            },
          }
      const result = await settingsApi.testProvider(provider, providerUpdate)
      setTestResult({ success: result.success, msg: result.message || result.errors.join('; ') })
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
    } catch (error) {
      setValidation({
        valid: false,
        errors: [`验证请求失败: ${error instanceof Error ? error.message : String(error)}`],
      })
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
    <div className="settings-page" style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%', overflow: 'hidden' }}>
      {/* Action bar */}
      <div className="settings-action-bar" style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: '12px',
      }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '15px', fontWeight: 600, letterSpacing: '-0.02em', marginRight: '16px' }}>
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
        ) : (
          <>
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
          </>
        )}
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
            <div className="settings-message" style={{
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
            <div className="settings-message" style={{
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
                  <div className="settings-provider-row" style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>DeepSeek API Key</label>
                      <input
                        type="password"
                        value={draft.deepseekKey}
                        onChange={e => setDraft({ ...draft, deepseekKey: e.target.value })}
                        placeholder={settings?.providers.deepseek.credential_configured ? '已配置；留空则保持不变' : 'sk-...'}
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
                  <div className="settings-provider-row" style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, marginBottom: '4px' }}>OpenAI API Key</label>
                      <input
                        type="password"
                        value={draft.openaiKey}
                        onChange={e => setDraft({ ...draft, openaiKey: e.target.value })}
                        placeholder={settings?.providers.openai.credential_configured ? '已配置；留空则保持不变' : 'sk-...'}
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
                  <div className="settings-message" style={{
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

                  {presets.length === 0 && (
                    <div style={{ fontSize: '13px', color: 'var(--muted)', padding: '16px', textAlign: 'center' }}>
                      未加载到内置预设，请检查后端配置。
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
        .settings-page,
        .settings-layout,
        .settings-panel,
        .settings-provider-row > div,
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
