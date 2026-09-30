import FlowPresetManager from '@/components/FlowPresetManager'
import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import { pipelineApi } from '@/api/pipeline'
import type { SettingsUpdate, SettingsView } from '@/api/settings'
import type { PresetItem } from '@/api/types'
import { useFileSelector } from '@/hooks/useFileSelector'

type SettingsTab = 'presets' | 'paths'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'presets', label: '流程预设' },
  { id: 'paths', label: '路径配置' },
]


export default function Settings() {
  const { selectFolder } = useFileSelector()
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState<SettingsTab>('presets')
  const [presets, setPresets] = useState<PresetItem[]>([])
  const [settingsLoadError, setSettingsLoadError] = useState('')
  const [presetsLoadError, setPresetsLoadError] = useState('')
  const [presetsLoading, setPresetsLoading] = useState(true)
  const loadGenerationRef = useRef(0)
  const presetGenerationRef = useRef(0)

  const [draft, setDraft] = useState({
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
    }
  }, [])

  const loadData = async () => {
    const generation = ++loadGenerationRef.current
    const presetGeneration = ++presetGenerationRef.current
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
          outputDir: current.paths.output_dir || '',
          vttDir: current.paths.vtt_dir || '',
          modelCacheDir: current.paths.model_cache_dir || '',
          tempDir: current.paths.temp_dir || '',
        })
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
            `无法加载流程预设：${presetsResult.reason instanceof Error ? presetsResult.reason.message : String(presetsResult.reason)}`,
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
      setPresetsLoadError(`无法加载流程预设：${error instanceof Error ? error.message : String(error)}`)
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
            内置与自定义 · 工作台共用
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

          {activeTab === 'presets' && <FlowPresetManager presets={presets} loading={presetsLoading} error={presetsLoadError} onReload={reloadPresets} />}

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
