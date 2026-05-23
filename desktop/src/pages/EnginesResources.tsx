import { useEffect, useState, useMemo } from 'react'
import { modelsApi } from '@/api/models'
import { tasksApi } from '@/api/tasks'
import { resourcesApi } from '@/api/resources'
import type { ModelSummaryResponse, ModelStatusResponse, ResourceStatusResponse } from '@/api/types'

type CategoryTab = 'llm' | 'asr' | 'tts' | 'other'

const CATEGORY_LABELS: Record<CategoryTab, string> = {
  llm: 'LLM',
  asr: 'ASR',
  tts: 'TTS',
  other: '其他',
}

const CATEGORY_COLORS: Record<string, { bg: string; fg: string }> = {
  llm: { bg: 'oklch(93% 0.03 320)', fg: 'oklch(45% 0.12 320)' },
  asr: { bg: 'oklch(93% 0.03 255)', fg: 'oklch(45% 0.14 255)' },
  tts: { bg: 'oklch(93% 0.04 170)', fg: 'oklch(40% 0.12 170)' },
  separator: { bg: 'oklch(93% 0.03 85)', fg: 'oklch(45% 0.12 85)' },
}

const STATUS_STYLES: Record<string, { dot: string; label: string }> = {
  installed: { dot: 'oklch(60% 0.16 145)', label: '已安装' },
  ready: { dot: 'oklch(60% 0.16 145)', label: '就绪' },
  loaded: { dot: 'oklch(60% 0.16 145)', label: '已加载' },
  configured: { dot: 'oklch(60% 0.16 145)', label: '已配置' },
  unconfigured: { dot: 'oklch(55% 0.18 25)', label: '未配置' },
  not_installed: { dot: 'oklch(55% 0.18 25)', label: '未安装' },
  missing: { dot: 'oklch(55% 0.18 25)', label: '未安装' },
  invalid: { dot: 'oklch(65% 0.14 85)', label: '不完整' },
  installing: { dot: 'oklch(65% 0.14 85)', label: '安装中' },
}

export default function EnginesResources() {
  const [resources, setResources] = useState<ResourceStatusResponse[]>([])
  const [models, setModels] = useState<ModelSummaryResponse[]>([])
  const [modelStatuses, setModelStatuses] = useState<ModelStatusResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<CategoryTab>('llm')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [installing, setInstalling] = useState<Record<string, { active: boolean; message?: string; progress?: number }>>({})

  useEffect(() => { loadData() }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [resData, modelData, statusData] = await Promise.all([
        resourcesApi.getStatus().catch(() => ({ resources: [] })),
        modelsApi.list().catch(() => []),
        modelsApi.statuses().catch(() => []),
      ])
      setResources(resData.resources)
      setModels(modelData)
      setModelStatuses(statusData)
    } finally {
      setLoading(false)
    }
  }

  const handleInstall = async (modelId: string) => {
    setInstalling(prev => ({ ...prev, [modelId]: { active: true, message: '准备下载...' } }))
    try {
      const res = await modelsApi.installAsync(modelId)
      if (res.task_id) {
        const pollInterval = setInterval(async () => {
          try {
            const taskRes = await tasksApi.get(res.task_id)
            if (taskRes.state === 'completed') {
              clearInterval(pollInterval)
              setInstalling(prev => ({ ...prev, [modelId]: { active: false } }))
              loadData()
            } else if (taskRes.state === 'failed') {
              clearInterval(pollInterval)
              setInstalling(prev => ({ ...prev, [modelId]: { active: false, message: taskRes.message || '安装失败' } }))
              loadData()
            } else {
              setInstalling(prev => ({
                ...prev,
                [modelId]: {
                  active: true,
                  message: taskRes.message || '下载中...',
                  progress: taskRes.progress,
                },
              }))
            }
          } catch {
            clearInterval(pollInterval)
            setInstalling(prev => ({ ...prev, [modelId]: { active: false } }))
            loadData()
          }
        }, 2000)
      } else {
        setInstalling(prev => ({ ...prev, [modelId]: { active: false } }))
        loadData()
      }
    } catch {
      setInstalling(prev => ({ ...prev, [modelId]: { active: false } }))
      loadData()
    }
  }

  const handleVerify = async (modelId: string) => {
    await modelsApi.verify(modelId).catch(() => { })
    loadData()
  }

  // Group models by category, then by family/backend
  const grouped = useMemo(() => {
    const byCategory: Record<string, ModelSummaryResponse[]> = {}
    for (const m of models) {
      const cat = m.category || 'other'
      if (!byCategory[cat]) byCategory[cat] = []
      byCategory[cat].push(m)
    }
    // Within each category, group by family_id or backend
    const result: Record<string, Record<string, ModelSummaryResponse[]>> = {}
    for (const [cat, catModels] of Object.entries(byCategory)) {
      result[cat] = {}
      for (const m of catModels) {
        const key = m.family_id || m.backend || m.display_name
        if (!result[cat][key]) result[cat][key] = []
        result[cat][key].push(m)
      }
    }
    return result
  }, [models])

  // Count per category tab
  const counts = useMemo(() => {
    const c: Record<CategoryTab, number> = { llm: 0, asr: 0, tts: 0, other: 0 }
    for (const m of models) {
      const cat = (m.category || 'other') as CategoryTab
      if (cat in c) c[cat]++
      else c.other++
    }
    return c
  }, [models])

  const getTabModels = (tab: CategoryTab) => {
    return grouped[tab] || {}
  }

  const getStatus = (modelId: string) => {
    return modelStatuses.find(s => s.model_id === modelId)
  }

  const toggleCollapse = (key: string) => {
    setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const getCatColor = (cat: string) => CATEGORY_COLORS[cat] || CATEGORY_COLORS.llm

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: 'var(--muted)' }}>
        加载中...
      </div>
    )
  }

  const tabGroups = getTabModels(activeTab)

  return (
    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%', overflow: 'hidden' }}>
      {/* Action bar */}
      <div style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: '12px',
      }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: '15px', fontWeight: 600, letterSpacing: '-0.02em', marginRight: '16px' }}>
          引擎与资源
        </h1>
        <button onClick={loadData} style={{
          fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500, padding: '7px 14px',
          borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
          color: 'var(--fg)', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '6px',
        }}>
          刷新状态
        </button>
      </div>

      {/* Content */}
      <div style={{ padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>

        {/* Runtime status cards */}
        <div>
          <div style={{
            fontSize: '11px', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.05em', marginBottom: '12px',
          }}>
            运行时状态
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
            {resources.map(res => (
              <div key={res.name} style={{
                background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', padding: '14px 16px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                  <div style={{
                    width: '8px', height: '8px', borderRadius: '50%',
                    background: res.available ? 'oklch(60% 0.16 145)' : 'oklch(55% 0.18 25)',
                  }} />
                  <span style={{ fontSize: '13px', fontWeight: 500 }}>{res.name}</span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--muted)' }}>{res.detail}</div>
              </div>
            ))}
            {resources.length === 0 && (
              <div style={{ fontSize: '13px', color: 'var(--muted)' }}>未检测到资源信息</div>
            )}
          </div>
        </div>

        {/* Model management */}
        <div>
          <div style={{
            fontSize: '11px', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase',
            letterSpacing: '0.05em', marginBottom: '12px',
          }}>
            模型管理
          </div>

          {/* Category tabs */}
          <div style={{
            display: 'flex', gap: '2px', background: 'var(--bg)', border: '1px solid var(--border)',
            borderRadius: '8px', padding: '3px', marginBottom: '16px',
          }}>
            {(Object.keys(CATEGORY_LABELS) as CategoryTab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                style={{
                  flex: 1, padding: '8px 12px', textAlign: 'center', fontSize: '13px', fontWeight: 500,
                  color: activeTab === tab ? 'var(--fg)' : 'var(--muted)',
                  background: activeTab === tab ? 'var(--surface)' : 'none',
                  boxShadow: activeTab === tab ? '0 1px 3px oklch(0% 0 0 / 0.08)' : 'none',
                  borderRadius: '6px', cursor: 'pointer', border: 'none', fontFamily: 'var(--font-body)',
                }}
              >
                {CATEGORY_LABELS[tab]}
                <span style={{
                  fontSize: '11px', color: 'var(--muted)', marginLeft: '4px', fontWeight: 400,
                }}>
                  {counts[tab]}
                </span>
              </button>
            ))}
          </div>

          {/* Model groups */}
          {Object.entries(tabGroups).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--muted)', padding: '16px' }}>该分类下暂无模型</div>
          ) : (
            Object.entries(tabGroups).map(([groupKey, groupModels]) => {
              const isCollapsed = !!collapsed[groupKey]
              const cat = groupModels[0]?.category || 'other'
              const catColor = getCatColor(cat)
              const catFg = catColor?.fg ?? 'var(--muted)'
              const catBg = catColor?.bg ?? 'var(--bg)'
              return (
                <div key={groupKey} style={{
                  background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px',
                  marginBottom: '12px', overflow: 'hidden',
                }}>
                  {/* Group header */}
                  <div
                    onClick={() => toggleCollapse(groupKey)}
                    style={{
                      padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '10px',
                      borderBottom: isCollapsed ? 'none' : '1px solid var(--border)',
                      cursor: 'pointer', userSelect: 'none',
                    }}
                  >
                    <svg
                      width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
                      style={{ flexShrink: 0, transition: 'transform 0.2s', color: 'var(--muted)', transform: isCollapsed ? 'rotate(-90deg)' : 'none' }}
                    >
                      <path d="M5 3l4 4-4 4" />
                    </svg>
                    <span style={{
                      padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 500,
                      background: catBg, color: catFg,
                    }}>
                      {CATEGORY_LABELS[cat as CategoryTab] || cat.toUpperCase()}
                    </span>
                    <span style={{ fontSize: '13px', fontWeight: 600 }}>{groupKey}</span>
                    <span style={{ fontSize: '11px', color: 'var(--muted)', marginLeft: 'auto' }}>
                      {groupModels.length} 个模型
                    </span>
                  </div>

                  {/* Group body */}
                  {!isCollapsed && (
                    <div>
                      {groupModels.map(model => {
                        const status = getStatus(model.model_id)
                        const statusInfo = status ? STATUS_STYLES[status.status] || STATUS_STYLES.not_installed : null
                        const installState = installing[model.model_id]
                        const isInstalling = !!installState?.active || status?.status === 'installing'
                        return (
                          <div key={model.model_id} style={{
                            display: 'grid', gridTemplateColumns: '1fr auto auto',
                            padding: '10px 16px', borderBottom: '1px solid var(--border)', alignItems: 'center',
                            fontSize: '13px', gap: '12px',
                          }}>
                            <div>
                              <div style={{ fontWeight: 500 }}>{model.display_name}</div>
                              <div style={{ fontSize: '11px', color: 'var(--muted)', marginTop: '2px' }}>
                                {model.backend || model.family_id || model.kind}
                              </div>
                            </div>
                            <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                              {statusInfo && (
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
                                  <span style={{
                                    width: '6px', height: '6px', borderRadius: '50%', background: statusInfo.dot,
                                    animation: isInstalling ? 'pulse 1.5s infinite' : 'none',
                                  }} />
                                  {statusInfo.label}
                                </span>
                              )}
                              {model.variant_tier === 'primary' && (
                                <span style={{
                                  fontSize: '10px', padding: '1px 6px', borderRadius: '3px', fontWeight: 500,
                                  background: 'oklch(95% 0.02 255)', color: 'var(--accent)',
                                }}>
                                  推荐
                                </span>
                              )}
                            </div>
                            <div style={{ display: 'flex', gap: '4px' }}>
                              {isInstalling ? (
                                <button disabled style={{
                                  fontFamily: 'var(--font-body)', fontSize: '12px', padding: '4px 10px',
                                  borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                                  color: 'var(--muted)', cursor: 'not-allowed',
                                }}>
                                  安装中...
                                </button>
                              ) : model.kind === 'cloud' ? (
                                /* Cloud models: no install/unload, only show config status */
                                null
                              ) : (
                                <>
                                  {(!status || status.status === 'not_installed' || status.status === 'missing' || status.status === 'invalid') && model.supports_install ? (
                                    <button onClick={() => handleInstall(model.model_id)} style={{
                                      fontFamily: 'var(--font-body)', fontSize: '12px', padding: '4px 10px',
                                      borderRadius: '6px', border: '1px solid var(--accent)', background: 'var(--accent)',
                                      color: 'white', cursor: 'pointer',
                                    }}>
                                      {status?.status === 'invalid' ? '重新安装' : '安装'}
                                    </button>
                                  ) : (
                                    <button onClick={() => handleVerify(model.model_id)} style={{
                                      fontFamily: 'var(--font-body)', fontSize: '12px', padding: '4px 10px',
                                      borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
                                      color: 'var(--fg)', cursor: 'pointer',
                                    }}>
                                      验证
                                    </button>
                                  )}
                                </>
                              )}
                            </div>
                            {isInstalling && (
                              <div style={{ gridColumn: '1 / -1', marginTop: '6px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                  <span style={{ fontSize: '11px', color: 'var(--muted)' }}>
                                    {installState?.message || '安装中...'}
                                  </span>
                                  {installState?.progress != null && installState.progress > 0 && (
                                    <span style={{ fontSize: '11px', color: 'var(--muted)' }}>
                                      {Math.round(installState.progress * 100)}%
                                    </span>
                                  )}
                                </div>
                                <div style={{ height: '3px', background: 'var(--border)', borderRadius: '2px', overflow: 'hidden' }}>
                                  <div style={{
                                    height: '100%', background: 'var(--accent)', borderRadius: '2px',
                                    width: installState?.progress ? `${Math.round(installState.progress * 100)}%` : '45%',
                                    animation: !installState?.progress ? 'progress-indeterminate 1.5s infinite' : 'none',
                                    transition: installState?.progress ? 'width 0.5s ease' : 'none',
                                  }} />
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes progress-indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }
      `}</style>
    </div>
  )
}
