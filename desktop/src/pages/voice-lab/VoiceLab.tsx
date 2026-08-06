import { useState, useEffect, useCallback } from 'react'
import { voiceApi } from '@/api/voice'
import type { VoiceProfileSummaryResponse, VoiceProfileResponse, SegmentInfo } from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

// ── Types ────────────────────────────────────────────
type FilterKind = 'all' | 'preset' | 'design' | 'clone'
type PanelType = 'preset' | 'design-create' | 'design-detail' | 'clone-create' | 'clone-detail' | 'empty'

interface ProfileGroup {
  engine: string
  label: string
  badge: string
  profiles: VoiceProfileSummaryResponse[]
}

// ── Styles ───────────────────────────────────────────
const S = {
  page: { display: 'grid', gridTemplateRows: 'auto 1fr', height: '100%', overflow: 'hidden' } as const,
  actionBar: {
    background: 'var(--surface)', borderBottom: '1px solid var(--border)',
    padding: '12px 24px', display: 'flex', alignItems: 'center', gap: '12px',
  } as const,
  title: {
    fontFamily: 'var(--font-display)', fontSize: '15px', fontWeight: 600,
    letterSpacing: '-0.02em', marginRight: '8px',
  } as const,
  gpuPill: {
    display: 'inline-flex', alignItems: 'center', gap: '4px',
    padding: '3px 10px', borderRadius: '10px', fontSize: '11px', fontWeight: 500,
    background: 'oklch(95% 0.02 255)', color: 'var(--accent)',
  } as const,
  spacer: { flex: 1 } as const,
  btn: {
    fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500,
    padding: '7px 14px', borderRadius: '6px', border: '1px solid var(--border)',
    background: 'var(--surface)', color: 'var(--fg)', cursor: 'pointer',
    display: 'inline-flex', alignItems: 'center', gap: '6px',
  } as const,
  btnPrimary: {
    fontFamily: 'var(--font-body)', fontSize: '13px', fontWeight: 500,
    padding: '7px 14px', borderRadius: '6px', border: '1px solid var(--accent)',
    background: 'var(--accent)', color: 'white', cursor: 'pointer',
    display: 'inline-flex', alignItems: 'center', gap: '6px',
  } as const,
  btnSm: {
    fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
    padding: '5px 10px', borderRadius: '6px', border: '1px solid var(--border)',
    background: 'var(--surface)', color: 'var(--fg)', cursor: 'pointer',
    display: 'inline-flex', alignItems: 'center', gap: '6px',
  } as const,
  btnPrimarySm: {
    fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
    padding: '5px 10px', borderRadius: '6px', border: '1px solid var(--accent)',
    background: 'var(--accent)', color: 'white', cursor: 'pointer',
    display: 'inline-flex', alignItems: 'center', gap: '6px',
  } as const,
  btnDanger: {
    fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
    padding: '5px 10px', borderRadius: '6px', border: '1px solid oklch(85% 0.06 25)',
    background: 'var(--surface)', color: 'var(--danger)', cursor: 'pointer',
  } as const,
  content: { display: 'grid', gridTemplateColumns: '260px 1fr', overflow: 'hidden' } as const,

  // Profile list
  list: {
    borderRight: '1px solid var(--border)', overflowY: 'auto', background: 'var(--surface)',
    display: 'flex', flexDirection: 'column',
  } as const,
  listHeader: {
    padding: '12px 16px', fontSize: '11px', fontWeight: 600, color: 'var(--muted)',
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
    borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  } as const,
  filterBar: {
    padding: '8px 12px', borderBottom: '1px solid var(--border)',
    display: 'flex', gap: '2px', background: 'var(--surface)',
  } as const,
  filterTab: (active: boolean) => ({
    padding: '4px 8px', fontSize: '11px', fontWeight: 500, borderRadius: '4px',
    cursor: 'pointer', color: active ? 'var(--fg)' : 'var(--muted)',
    background: active ? 'var(--bg)' : 'transparent', border: 'none', fontFamily: 'var(--font-body)',
  } as const),
  groupHeader: {
    padding: '10px 16px', fontSize: '12px', fontWeight: 600, color: 'var(--fg)',
    display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', userSelect: 'none' as const,
  } as const,
  badge: {
    padding: '1px 6px', borderRadius: '3px', fontSize: '10px', fontWeight: 600,
    background: 'oklch(95% 0.02 255)', color: 'var(--accent)',
  } as const,
  badgeCount: {
    background: 'var(--bg)', color: 'var(--muted)', fontSize: '10px',
    padding: '1px 5px', borderRadius: '3px', marginLeft: 'auto',
  } as const,
  chevron: (collapsed: boolean) => ({
    width: 12, height: 12, color: 'var(--muted)', flexShrink: 0,
    transition: 'transform 0.15s', transform: collapsed ? 'rotate(-90deg)' : 'rotate(0)',
  } as const),
  profileItem: (selected: boolean) => ({
    padding: selected ? '9px 16px 9px 29px' : '9px 16px 9px 32px',
    fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px',
    color: 'var(--fg)', borderLeft: selected ? '3px solid var(--accent)' : '3px solid transparent',
    background: selected ? 'oklch(97% 0.01 255)' : 'transparent',
    transition: 'background 0.1s, border-color 0.1s',
  } as const),
  availDot: (ok: boolean) => ({
    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
    background: ok ? 'var(--success)' : 'oklch(70% 0.08 50)',
  } as const),
  itemName: { flex: 1, whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' as const },
  itemSpeaker: {
    fontSize: '10px', color: 'var(--muted)', fontFamily: 'var(--font-mono)',
    maxWidth: 90, whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' as const,
  },
  groupEmpty: { padding: '12px 16px 12px 32px', fontSize: '11px', color: 'var(--muted)', fontStyle: 'italic' },

  // Work panel
  workPanel: {
    padding: '20px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px',
  } as const,
  panel: {
    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px',
  } as const,
  panelHeader: {
    padding: '12px 16px', fontSize: '13px', fontWeight: 600,
    borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '8px',
  } as const,
  panelSubtitle: { fontWeight: 400, color: 'var(--muted)', fontSize: '12px' } as const,
  panelBody: { padding: '16px' } as const,
  detailGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' } as const,
  label: { fontSize: '11px', color: 'var(--muted)', marginBottom: '2px' } as const,
  value: { fontSize: '13px', fontWeight: 500 } as const,
  valueMono: { fontSize: '12px', fontFamily: 'var(--font-mono)', fontWeight: 500 } as const,
  valueMuted: { fontSize: '13px', fontWeight: 400, color: 'var(--muted)' } as const,
  formGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' } as const,
  formField: { display: 'flex', flexDirection: 'column' as const, gap: '4px' } as const,
  formLabel: {
    fontSize: '11px', fontWeight: 500, color: 'var(--muted)',
    textTransform: 'uppercase' as const, letterSpacing: '0.04em',
  } as const,
  input: {
    fontFamily: 'var(--font-body)', fontSize: '13px', padding: '8px 10px',
    borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
    color: 'var(--fg)', width: '100%', outline: 'none',
  } as const,
  textarea: {
    fontFamily: 'var(--font-body)', fontSize: '13px', padding: '8px 10px',
    borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--surface)',
    color: 'var(--fg)', width: '100%', minHeight: 80, lineHeight: 1.5, resize: 'vertical' as const, outline: 'none',
  } as const,
  hint: { fontSize: '11px', color: 'var(--muted)', marginTop: '2px' } as const,
  actionsRow: { display: 'flex', gap: '8px', alignItems: 'center', paddingTop: '12px' } as const,
  previewBar: {
    display: 'flex', alignItems: 'center', gap: '10px', padding: '14px 16px',
    borderTop: '1px solid var(--border)',
  } as const,
  tag: (variant: 'preset' | 'design' | 'clone' | 'ready' | 'unavail') => {
    const colors = {
      preset: { bg: 'oklch(95% 0.02 255)', fg: 'var(--accent)' },
      design: { bg: 'oklch(93% 0.03 145)', fg: 'oklch(40% 0.12 145)' },
      clone: { bg: 'oklch(93% 0.03 85)', fg: 'oklch(45% 0.10 85)' },
      ready: { bg: 'oklch(94% 0.03 145)', fg: 'oklch(38% 0.10 145)' },
      unavail: { bg: 'oklch(94% 0.02 50)', fg: 'oklch(50% 0.08 50)' },
    }
    return {
      display: 'inline-flex', padding: '2px 8px', borderRadius: '4px',
      fontSize: '11px', fontWeight: 500, background: colors[variant].bg, color: colors[variant].fg,
    } as const
  },
  uploadZone: {
    border: '2px dashed var(--border)', borderRadius: '8px', padding: '24px', textAlign: 'center' as const,
    color: 'var(--muted)', fontSize: '13px', cursor: 'pointer',
  } as const,
  segmentTable: {
    width: '100%', borderCollapse: 'collapse' as const, fontSize: '12px', marginTop: '8px',
  } as const,
  segTh: {
    textAlign: 'left' as const, fontSize: '10px', fontWeight: 600, color: 'var(--muted)',
    textTransform: 'uppercase' as const, letterSpacing: '0.04em',
    padding: '6px 8px', borderBottom: '1px solid var(--border)',
  } as const,
  segTd: { padding: '6px 8px', borderBottom: '1px solid var(--border)', verticalAlign: 'middle' as const },
  emptyState: {
    display: 'flex', flexDirection: 'column' as const, alignItems: 'center', justifyContent: 'center',
    height: '100%', color: 'var(--muted)', fontSize: '13px', gap: '12px', textAlign: 'center' as const,
  } as const,
}

// ── SVG Icons ────────────────────────────────────────
const PlusIcon = () => (
  <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M7 3v8M3 7h8"/></svg>
)
const PlayIcon = () => (
  <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 2l7 4-7 4V2z" fill="currentColor" stroke="none"/></svg>
)
const ChevronIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 3l4 3-4 3"/></svg>
)
const UploadIcon = () => (
  <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginBottom: 4 }}>
    <path d="M12 5v10M8 11l4 4 4-4"/><path d="M4 17v2h16v-2"/>
  </svg>
)

// ── Group engine → label mapping ─────────────────────
const ENGINE_GROUPS: Record<string, { label: string; badge: string }> = {
  qwen3_custom: { label: 'CustomVoice 预设', badge: 'Qwen3' },
  qwen3_design: { label: 'VoiceDesign 设计', badge: 'Qwen3' },
  qwen3_clone: { label: '克隆音色', badge: 'Qwen3' },
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

// ── Component ────────────────────────────────────────
export default function VoiceLab() {
  const { selectFiles } = useFileSelector()
  const showAudio = useAudioPlayerStore((state) => state.show)
  const [profiles, setProfiles] = useState<VoiceProfileSummaryResponse[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<VoiceProfileResponse | null>(null)
  const [filter, setFilter] = useState<FilterKind>('all')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [panel, setPanel] = useState<PanelType>('empty')

  // Create form state
  const [designName, setDesignName] = useState('')
  const [designDesc, setDesignDesc] = useState('')
  const [designRefText, setDesignRefText] = useState('')
  const [cloneName, setCloneName] = useState('')
  const [cloneRefText, setCloneRefText] = useState('')
  const [cloneAudioPath, setCloneAudioPath] = useState('')
  const [cloneSubtitlePath, setCloneSubtitlePath] = useState('')
  const [cloneAudioLanguage, setCloneAudioLanguage] = useState('ja')

  // Preview state
  const [previewText, setPreviewText] = useState('哥哥，今天给你做个特别的按摩哦，先从肩膀开始，放松一下吧。')
  const [previewAudio, setPreviewAudio] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // Instruct editing
  const [instructValue, setInstructValue] = useState('')

  // Segment analysis
  const [segments, setSegments] = useState<SegmentInfo[]>([])
  const [recommendedIndices, setRecommendedIndices] = useState<number[]>([])
  const [analysisWarnings, setAnalysisWarnings] = useState<string[]>([])
  const [analyzing, setAnalyzing] = useState(false)

  // Design result
  const [designResult, setDesignResult] = useState<{ ref_audio_path: string; prompt_cache_path: string } | null>(null)

  // Loading states
  const [designing, setDesigning] = useState(false)
  const [cloning, setCloning] = useState(false)
  const [actionError, setActionError] = useState('')

  // ── Load profiles ──────────────────────────────────
  const loadProfiles = useCallback(async () => {
    try {
      const data = await voiceApi.listProfiles()
      setProfiles(data)
    } catch (error) {
      setProfiles([])
      setActionError(`加载音色失败：${errorMessage(error)}`)
    }
  }, [])

  useEffect(() => { loadProfiles() }, [loadProfiles])

  // ── Select profile ─────────────────────────────────
  const handleSelect = useCallback(async (id: string, category: string) => {
    setActionError('')
    setSelectedId(id)
    setPreviewAudio(null)
    setDesignResult(null)
    setSegments([])
    setRecommendedIndices([])
    setAnalysisWarnings([])

    if (category === 'preset') {
      try {
        const d = await voiceApi.getProfile(id)
        setDetail(d)
        setInstructValue(d.instruct || '')
        setPanel('preset')
      } catch (error) {
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    } else if (category === 'custom') {
      try {
        const d = await voiceApi.getProfile(id)
        setDetail(d)
        setPanel('design-detail')
      } catch (error) {
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    } else if (category === 'clone') {
      try {
        const d = await voiceApi.getProfile(id)
        setDetail(d)
        setPanel('clone-detail')
      } catch (error) {
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    }
  }, [])

  // ── Actions ────────────────────────────────────────
  const handlePreview = useCallback(async () => {
    if (!selectedId) return
    setActionError('')
    setPreviewLoading(true)
    try {
      const res = await voiceApi.preview(selectedId, { text: previewText, speed: 1.0 })
      setPreviewAudio(res.audio_path)
      showAudio(res.audio_path, `音色试听 · ${detail?.name || selectedId}`)
      useAudioPlayerStore.getState().setPlaying(true)
    } catch (error) {
      setActionError(`试听生成失败：${errorMessage(error)}`)
    } finally {
      setPreviewLoading(false)
    }
  }, [detail?.name, previewText, selectedId, showAudio])

  const handleDesign = useCallback(async () => {
    if (!designName || !designDesc) return
    setActionError('')
    setDesigning(true)
    try {
      const res = await voiceApi.design({ name: designName, description: designDesc, ref_text: designRefText || undefined })
      setDesignResult({ ref_audio_path: res.ref_audio_path, prompt_cache_path: res.prompt_cache_path })
      await loadProfiles()
      setDetail(await voiceApi.getProfile(res.profile_id))
      setSelectedId(res.profile_id)
      setPanel('design-detail')
    } catch (error) {
      setActionError(`音色设计失败：${errorMessage(error)}`)
    } finally {
      setDesigning(false)
    }
  }, [designName, designDesc, designRefText, loadProfiles])

  const handleAnalyze = useCallback(async () => {
    if (!cloneAudioPath) return
    setActionError('')
    setSegments([])
    setRecommendedIndices([])
    setAnalysisWarnings([])
    setAnalyzing(true)
    try {
      const res = await voiceApi.analyzeSegments({
        audio_path: cloneAudioPath,
        subtitle_path: cloneSubtitlePath || undefined,
        audio_language: cloneAudioLanguage,
      })
      setSegments(res.segments)
      setRecommendedIndices(res.recommended_indices)
      setAnalysisWarnings(res.warnings)
    } catch (error) {
      setActionError(`音频分析失败：${errorMessage(error)}`)
    } finally {
      setAnalyzing(false)
    }
  }, [cloneAudioLanguage, cloneAudioPath, cloneSubtitlePath])

  const handleClone = useCallback(async () => {
    if (!cloneAudioPath || !cloneName) return
    setActionError('')
    setCloning(true)
    try {
      const res = await voiceApi.clone({ audio_path: cloneAudioPath, name: cloneName, ref_text: cloneRefText || undefined })
      await loadProfiles()
      setDetail(await voiceApi.getProfile(res.profile_id))
      setSelectedId(res.profile_id)
      setPanel('clone-detail')
    } catch (error) {
      setActionError(`音色克隆失败：${errorMessage(error)}`)
    } finally {
      setCloning(false)
    }
  }, [cloneAudioPath, cloneName, cloneRefText, loadProfiles])

  const handleDelete = useCallback(async () => {
    if (!selectedId) return
    setActionError('')
    try {
      await voiceApi.deleteProfile(selectedId)
      setSelectedId(null)
      setDetail(null)
      setPanel('empty')
      await loadProfiles()
    } catch (error) {
      setActionError(`删除音色失败：${errorMessage(error)}`)
    }
  }, [selectedId, loadProfiles])

  const handleSelectCloneAudio = useCallback(async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.audio],
      browserPrompt: '请输入参考音频所在目录的完整路径：',
    })
    if (files.length > 0) {
      setCloneAudioPath(files[0]!)
      setActionError('')
    }
  }, [selectFiles])

  const handleSelectCloneSubtitle = useCallback(async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.subtitle],
      browserPrompt: '请输入参考字幕文件的完整路径：',
    })
    if (files.length > 0) {
      setCloneSubtitlePath(files[0]!)
      setActionError('')
    }
  }, [selectFiles])

  const showCreate = (type: 'design' | 'clone') => {
    setSelectedId(null)
    setDetail(null)
    setDesignResult(null)
    setSegments([])
    setRecommendedIndices([])
    setAnalysisWarnings([])
    if (type === 'design') {
      setDesignName(''); setDesignDesc(''); setDesignRefText('')
      setPanel('design-create')
    } else {
      setCloneName(''); setCloneRefText(''); setCloneAudioPath(''); setCloneSubtitlePath(''); setCloneAudioLanguage('ja')
      setPanel('clone-create')
    }
  }

  // ── Build groups ───────────────────────────────────
  const groups: ProfileGroup[] = Object.entries(ENGINE_GROUPS).map(([engine, meta]) => ({
    engine,
    label: meta.label,
    badge: meta.badge,
    profiles: profiles.filter(profile => {
      if (engine === 'qwen3_custom') return profile.category === 'preset'
      if (engine === 'qwen3_design') return profile.category === 'custom'
      return profile.category === 'clone'
    }),
  }))

  const filteredGroups = filter === 'all'
    ? groups
    : groups.filter(g => {
        if (filter === 'preset') return g.engine === 'qwen3_custom'
        if (filter === 'design') return g.engine === 'qwen3_design'
        if (filter === 'clone') return g.engine === 'qwen3_clone'
        return true
      })

  const totalCount = profiles.length
  const counts: Record<FilterKind, number> = {
    all: totalCount,
    preset: profiles.filter(p => p.category === 'preset').length,
    design: profiles.filter(p => p.category === 'custom').length,
    clone: profiles.filter(p => p.category === 'clone').length,
  }

  // ── Render helpers ─────────────────────────────────
  const renderFilterTab = (kind: FilterKind, label: string) => (
    <button style={S.filterTab(filter === kind)} onClick={() => setFilter(kind)}>
      {label}<span style={{ marginLeft: 3, fontSize: 10, opacity: 0.7 }}>{counts[kind]}</span>
    </button>
  )

  const renderDetailField = (label: string, value: string, opts?: { mono?: boolean; muted?: boolean; full?: boolean }) => (
    <div style={opts?.full ? { gridColumn: '1 / -1' } : undefined}>
      <div style={S.label}>{label}</div>
      <div style={opts?.mono ? S.valueMono : opts?.muted ? S.valueMuted : S.value}>{value}</div>
    </div>
  )

  // ── Panel rendering ────────────────────────────────
  const renderPanel = () => {
    switch (panel) {
      case 'preset':
        if (!detail) return null
        return (
          <>
            {/* Detail */}
            <div style={S.panel}>
              <div style={S.panelHeader}>
                音色详情
                <span style={S.panelSubtitle}>— Qwen3 CustomVoice 预设</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('preset')}>预设</span></div>
              </div>
              <div style={S.panelBody}>
                <div style={S.detailGrid}>
                  {renderDetailField('名称', detail.name)}
                  {renderDetailField('ID', detail.id, { mono: true })}
                  {renderDetailField('引擎', detail.engine)}
                  {renderDetailField('Speaker', detail.speaker || '—')}
                  {renderDetailField('状态', detail.available ? '可用' : '不可用')}
                  {renderDetailField('分类', detail.category)}
                  {renderDetailField('描述', detail.description || '—', { muted: true, full: true })}
                </div>
              </div>
            </div>

            {/* Instruct editing */}
            <div style={S.panel}>
              <div style={S.panelHeader}>语气控制 (Instruct)</div>
              <div style={S.panelBody}>
                <div style={S.formGrid}>
                  <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                    <label style={S.formLabel}>Instruct 指令</label>
                    <input
                      style={S.input}
                      type="text"
                      value={instructValue}
                      onChange={e => setInstructValue(e.target.value)}
                      placeholder="如：用撒娇的语气说、用低沉性感的声音说"
                    />
                    <span style={S.hint}>控制 CustomVoice 的语气和情感表达。留空则使用默认语气。</span>
                  </div>
                </div>
                <div style={S.actionsRow}>
                  <button
                    style={{ ...S.btnSm, cursor: 'not-allowed', opacity: 0.5 }}
                    disabled
                    title="当前后端未提供音色更新接口"
                  >
                    保存修改（暂不可用）
                  </button>
                  <button
                    style={{ ...S.btnDanger, cursor: 'not-allowed', opacity: 0.5 }}
                    disabled
                    title="内置预设音色不能删除"
                  >
                    内置预设不可删除
                  </button>
                </div>
              </div>
            </div>

            {/* Preview */}
            {renderPreviewPanel()}
          </>
        )

      case 'design-create':
        return (
          <div style={S.panel}>
            <div style={S.panelHeader}>
              音色设计
              <span style={S.panelSubtitle}>— 自然语言描述生成新音色</span>
              <div style={{ marginLeft: 'auto' }}><span style={S.tag('design')}>VoiceDesign</span></div>
            </div>
            <div style={S.panelBody}>
              <div style={S.formGrid}>
                <div style={S.formField}>
                  <label style={S.formLabel}>配置名称 *</label>
                  <input style={S.input} type="text" value={designName} onChange={e => setDesignName(e.target.value)} placeholder="给这个音色起个名字" />
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>参考文本 (可选)</label>
                  <input style={S.input} type="text" value={designRefText} onChange={e => setDesignRefText(e.target.value)} placeholder="生成时朗读的文本" />
                </div>
                <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                  <label style={S.formLabel}>音色描述 (design_instruct) *</label>
                  <textarea
                    style={S.textarea}
                    value={designDesc}
                    onChange={e => setDesignDesc(e.target.value)}
                    placeholder={'用自然语言描述想要的声音特征，例如：\n- 温柔的成年女性声音，语速偏慢，带有轻微的气声感，适合耳语场景\n- 活泼的少女声线，语调上扬，带有俏皮感'}
                  />
                  <span style={S.hint}>VoiceDesign 模型会根据描述生成对应音色的参考音频和 prompt cache。</span>
                </div>
              </div>
              <div style={S.actionsRow}>
                <button style={S.btnPrimarySm} onClick={handleDesign} disabled={designing}>
                  {designing ? '生成中...' : '生成音色'}
                </button>
              </div>
            </div>
          </div>
        )

      case 'design-detail':
        if (!detail) return null
        return (
          <>
            <div style={S.panel}>
              <div style={S.panelHeader}>
                设计音色详情
                <span style={S.panelSubtitle}>— VoiceDesign 生成</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('design')}>VoiceDesign</span></div>
              </div>
              <div style={S.panelBody}>
                <div style={S.detailGrid}>
                  {renderDetailField('名称', detail.name)}
                  {renderDetailField('ID', detail.id, { mono: true })}
                  {renderDetailField('状态', detail.available ? '已生成' : '待生成')}
                  {renderDetailField('引擎', 'qwen3_design')}
                  {renderDetailField('音色描述', detail.design_instruct || detail.description || '—', { muted: true, full: true })}
                  {renderDetailField('参考音频', detail.ref_audio || '—', { mono: true, full: true })}
                </div>
                <div style={S.actionsRow}>
                  <button style={S.btnSm} onClick={() => showCreate('design')}>重新生成</button>
                  <button style={S.btnDanger} onClick={handleDelete}>删除音色</button>
                </div>
              </div>
            </div>
            {designResult && (
              <div style={S.panel}>
                <div style={S.panelHeader}>生成结果<span style={S.panelSubtitle}>— ref_audio + prompt_cache 已生成</span></div>
                <div style={S.panelBody}>
                  <div style={S.detailGrid}>
                    {renderDetailField('参考音频路径', designResult.ref_audio_path, { mono: true, full: true })}
                    {renderDetailField('Prompt Cache 路径', designResult.prompt_cache_path, { mono: true, full: true })}
                  </div>
                </div>
              </div>
            )}
            {renderPreviewPanel()}
          </>
        )

      case 'clone-create':
        return (
          <div style={S.panel}>
            <div style={S.panelHeader}>
              音色克隆
              <span style={S.panelSubtitle}>— 从参考音频提取音色特征</span>
              <div style={{ marginLeft: 'auto' }}><span style={S.tag('clone')}>Clone</span></div>
            </div>
            <div style={S.panelBody}>
              <div style={S.formGrid}>
                <div style={S.formField}>
                  <label style={S.formLabel}>配置名称 *</label>
                  <input style={S.input} type="text" value={cloneName} onChange={e => setCloneName(e.target.value)} placeholder="克隆音色名称" />
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>参考文本 (可选)</label>
                  <input style={S.input} type="text" value={cloneRefText} onChange={e => setCloneRefText(e.target.value)} placeholder="参考音频中说的内容，提升克隆质量" />
                </div>
                <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                  <label style={S.formLabel}>参考音频 *</label>
                  <div
                    style={S.uploadZone}
                    onClick={handleSelectCloneAudio}
                  >
                    <UploadIcon />
                    <div>{cloneAudioPath || '点击选择参考音频文件 (.wav / .mp3)'}</div>
                    <div style={{ fontSize: 11, marginTop: 4 }}>建议 5-30 秒清晰人声，无背景音</div>
                  </div>
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>参考字幕 (可选)</label>
                  <button style={S.btnSm} type="button" onClick={handleSelectCloneSubtitle}>
                    {cloneSubtitlePath ? '更换字幕' : '选择字幕'}
                  </button>
                  <span style={S.hint}>{cloneSubtitlePath || '未提供时使用 ASR 识别音频文本'}</span>
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>音频语言</label>
                  <select style={S.input} value={cloneAudioLanguage} onChange={event => setCloneAudioLanguage(event.target.value)}>
                    <option value="ja">日语</option>
                    <option value="zh">中文</option>
                    <option value="en">英语</option>
                  </select>
                </div>
              </div>

              {/* Segment analysis */}
              {segments.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
                    片段分析结果
                  </div>
                  <table style={S.segmentTable}>
                    <thead>
                      <tr>
                        <th style={S.segTh}>#</th>
                        <th style={S.segTh}>时间</th>
                        <th style={S.segTh}>文本</th>
                        <th style={S.segTh}>评分</th>
                        <th style={S.segTh}>标签</th>
                      </tr>
                    </thead>
                    <tbody>
                      {segments.map((seg) => (
                        <tr key={seg.index} style={recommendedIndices.includes(seg.index) ? { background: 'oklch(97% 0.01 145)' } : undefined}>
                          <td style={{ ...S.segTd, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>{seg.index}</td>
                          <td style={{ ...S.segTd, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>{seg.start.toFixed(1)} – {seg.end.toFixed(1)}s</td>
                          <td style={S.segTd}>{seg.text}</td>
                          <td style={S.segTd}>
                            <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 11, color: seg.score >= 80 ? 'var(--success)' : 'var(--warning)' }}>
                              {seg.score}
                            </span>
                          </td>
                          <td style={S.segTd}>
                            {recommendedIndices.includes(seg.index)
                              ? <span style={S.tag('ready')}>推荐</span>
                              : (seg.label || '—')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {analysisWarnings.length > 0 && (
                    <div style={{ ...S.hint, marginTop: 8 }}>
                      {analysisWarnings.join('；')}
                    </div>
                  )}
                </div>
              )}

              <div style={S.actionsRow}>
                <button style={S.btnSm} onClick={handleAnalyze} disabled={analyzing || !cloneAudioPath}>
                  {analyzing ? '分析中...' : '分析片段'}
                </button>
                <button style={S.btnPrimarySm} onClick={handleClone} disabled={cloning || !cloneName || !cloneAudioPath}>
                  {cloning ? '克隆中...' : '开始克隆'}
                </button>
              </div>
            </div>
          </div>
        )

      case 'clone-detail':
        if (!detail) return null
        return (
          <>
            <div style={S.panel}>
              <div style={S.panelHeader}>
                克隆音色详情
                <span style={S.panelSubtitle}>— 从参考音频提取</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('clone')}>Clone</span></div>
              </div>
              <div style={S.panelBody}>
                <div style={S.detailGrid}>
                  {renderDetailField('名称', detail.name)}
                  {renderDetailField('ID', detail.id, { mono: true })}
                  {renderDetailField('状态', detail.available ? '已缓存' : '未缓存')}
                  {renderDetailField('引擎', 'qwen3_clone')}
                  {renderDetailField('参考音频', detail.ref_audio || '—', { mono: true, full: true })}
                  {renderDetailField('描述', detail.description || '—', { muted: true, full: true })}
                </div>
                <div style={S.actionsRow}>
                  <button style={S.btnDanger} onClick={handleDelete}>删除音色</button>
                </div>
              </div>
            </div>
            {renderPreviewPanel()}
          </>
        )

      case 'empty':
      default:
        return (
          <div style={S.emptyState}>
            <svg width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1" opacity={0.3}>
              <path d="M24 8v32M16 14v20M32 12v24M40 20v8M8 20v8" />
            </svg>
            <div>选择一个音色查看详情，或点击「新建音色」创建</div>
          </div>
        )
    }
  }

  const renderPreviewPanel = () => (
    <div style={S.panel}>
      <div style={S.panelHeader}>试听</div>
      <div style={S.previewBar}>
        <input
          style={{ ...S.input, flex: 1, background: 'var(--bg)' }}
          type="text"
          value={previewText}
          onChange={e => setPreviewText(e.target.value)}
          placeholder="输入试听文本"
        />
        <button style={S.btnPrimarySm} onClick={handlePreview} disabled={previewLoading}>
          <PlayIcon /> {previewLoading ? '生成中...' : '试听'}
        </button>
      </div>
      {previewAudio && (
        <div style={{ padding: '8px 16px 12px', fontSize: 11, color: 'var(--muted)' }}>
          已生成并载入播放器: {previewAudio}
        </div>
      )}
    </div>
  )

  // ── Main render ────────────────────────────────────
  return (
    <div style={S.page}>
      {/* Action bar */}
      <div style={S.actionBar}>
        <span style={S.title}>音色实验室</span>
        {actionError && (
          <span style={{ color: 'var(--danger)', fontSize: 12 }} title={actionError}>
            {actionError}
          </span>
        )}
        <span style={S.gpuPill}>Qwen3 扩展</span>
        <div style={S.spacer} />
        <button style={S.btn} onClick={() => showCreate('design')}>
          <PlusIcon /> 新建音色
        </button>
      </div>

      {/* Content: list + work panel */}
      <div style={S.content}>
        {/* Profile list */}
        <div style={S.list}>
          <div style={S.listHeader}>
            <span>音色列表</span>
            <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}>{totalCount} 个</span>
          </div>

          {/* Filter tabs */}
          <div style={S.filterBar}>
            {renderFilterTab('all', '全部')}
            {renderFilterTab('preset', '预设')}
            {renderFilterTab('design', '设计')}
            {renderFilterTab('clone', '克隆')}
          </div>

          {/* Model groups */}
          {filteredGroups.map(group => {
            const isCollapsed = collapsed[group.engine] || false
            return (
              <div key={group.engine} style={{ borderBottom: '1px solid var(--border)' }}>
                <div
                  style={S.groupHeader}
                  onClick={() => setCollapsed(c => ({ ...c, [group.engine]: !c[group.engine] }))}
                >
                  <span style={{ ...S.chevron(isCollapsed), display: 'inline-flex', alignItems: 'center' }}>
                    <ChevronIcon />
                  </span>
                  <span style={S.badge}>{group.badge}</span>
                  {group.label}
                  <span style={S.badgeCount}>{group.profiles.length}</span>
                </div>
                {!isCollapsed && (
                  <div>
                    {group.profiles.length === 0 ? (
                      <div style={S.groupEmpty}>
                        {group.engine === 'qwen3_custom' ? '暂无预设音色' : `暂无${group.label}，点击「新建音色」创建`}
                      </div>
                    ) : (
                      group.profiles.map(p => (
                        <div
                          key={p.id}
                          style={S.profileItem(selectedId === p.id)}
                          onClick={() => handleSelect(p.id, p.category)}
                        >
                          <span style={S.availDot(p.available)} />
                          <span style={S.itemName}>{p.name}</span>
                          <span style={S.itemSpeaker}>{p.category}</span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Work panel */}
        <div style={S.workPanel}>
          {renderPanel()}
        </div>
      </div>
    </div>
  )
}
