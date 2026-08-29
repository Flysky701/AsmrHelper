import { useState, useEffect, useCallback, useRef } from 'react'
import { voiceApi } from '@/api/voice'
import type { VoiceProfileSummaryResponse, VoiceProfileResponse, VoiceCloneCandidate } from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import type { TaskStatus } from '@/stores/taskStore'

// ── Types ────────────────────────────────────────────
type FilterKind = 'all' | 'preset' | 'design' | 'clone'
type PanelType = 'preset' | 'design-create' | 'design-detail' | 'clone-create' | 'clone-detail' | 'empty'
type CloneMode = 'icl' | 'x-vector'

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

const QWEN_LANGUAGE_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日语' },
  { value: 'en', label: '英语' },
  { value: 'ko', label: '韩语' },
  { value: 'de', label: '德语' },
  { value: 'fr', label: '法语' },
  { value: 'ru', label: '俄语' },
  { value: 'pt', label: '葡萄牙语' },
  { value: 'es', label: '西班牙语' },
  { value: 'it', label: '意大利语' },
]

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function candidateSourceLabel(sourceVariant: string): string {
  if (sourceVariant === 'separated' || sourceVariant === 'vocals' || sourceVariant === 'separated_vocals') return '分离人声'
  if (sourceVariant === 'original') return '原始音频'
  return sourceVariant || '未知来源'
}

function detailValue(value: unknown): string {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'string' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

function candidateDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${detailValue(value)}`)
    .join(' · ')
}

// ── Component ────────────────────────────────────────
export default function VoiceLab() {
  const { selectFiles } = useFileSelector()
  const setPage = useNavStore((state) => state.setPage)
  const addTask = useTaskStore((state) => state.addTask)
  const updateTask = useTaskStore((state) => state.updateTask)
  const showAudio = useAudioPlayerStore((state) => state.show)
  const seekAudio = useAudioPlayerStore((state) => state.seek)
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
  const [cloneMode, setCloneMode] = useState<CloneMode>('icl')
  const [separateVocals, setSeparateVocals] = useState(false)

  // Preview state
  const [previewText, setPreviewText] = useState('哥哥，今天给你做个特别的按摩哦，先从肩膀开始，放松一下吧。')
  const [previewLanguage, setPreviewLanguage] = useState('zh')
  const [previewLoading, setPreviewLoading] = useState(false)

  // Instruct editing
  const [instructValue, setInstructValue] = useState('')

  // Segment analysis
  const [analysisId, setAnalysisId] = useState('')
  const [sourceFingerprint, setSourceFingerprint] = useState('')
  const [candidates, setCandidates] = useState<VoiceCloneCandidate[]>([])
  const [recommendedCandidateId, setRecommendedCandidateId] = useState<string | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const [analysisWarnings, setAnalysisWarnings] = useState<string[]>([])
  const [analyzing, setAnalyzing] = useState(false)
  const analysisRequestId = useRef(0)
  const selectionRequestId = useRef(0)

  // Loading states
  const [designing, setDesigning] = useState(false)
  const [cloning, setCloning] = useState(false)
  const [actionError, setActionError] = useState('')

  // ── Load profiles ──────────────────────────────────
  const loadProfiles = useCallback(async (invalidateSelection = true) => {
    if (invalidateSelection) selectionRequestId.current += 1
    try {
      const data = await voiceApi.listProfiles()
      setProfiles(data)
    } catch (error) {
      setProfiles([])
      setActionError(`加载音色失败：${errorMessage(error)}`)
    }
  }, [])

  useEffect(() => { loadProfiles() }, [loadProfiles])

  const invalidateAnalysis = useCallback(() => {
    analysisRequestId.current += 1
    setAnalysisId('')
    setSourceFingerprint('')
    setCandidates([])
    setRecommendedCandidateId(null)
    setSelectedCandidateId(null)
    setCloneRefText('')
    setAnalysisWarnings([])
    setAnalyzing(false)
  }, [])

  // ── Select profile ─────────────────────────────────
  const handleSelect = useCallback(async (id: string, category: string) => {
    const requestId = ++selectionRequestId.current
    setActionError('')
    setSelectedId(id)
    setDetail(null)
    setPanel('empty')
    invalidateAnalysis()

    if (category === 'preset') {
      try {
        const d = await voiceApi.getProfile(id)
        if (requestId !== selectionRequestId.current) return
        setDetail(d)
        setInstructValue(d.instruct || '')
        setPanel('preset')
      } catch (error) {
        if (requestId !== selectionRequestId.current) return
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    } else if (category === 'custom') {
      try {
        const d = await voiceApi.getProfile(id)
        if (requestId !== selectionRequestId.current) return
        setDetail(d)
        setPanel('design-detail')
      } catch (error) {
        if (requestId !== selectionRequestId.current) return
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    } else if (category === 'clone') {
      try {
        const d = await voiceApi.getProfile(id)
        if (requestId !== selectionRequestId.current) return
        setDetail(d)
        setPanel('clone-detail')
      } catch (error) {
        if (requestId !== selectionRequestId.current) return
        setActionError(`读取音色详情失败：${errorMessage(error)}`)
        setPanel('empty')
      }
    }
  }, [invalidateAnalysis])

  // ── Actions ────────────────────────────────────────
  const handlePreview = useCallback(async () => {
    const text = previewText.trim()
    if (!selectedId || !text) return
    setActionError('')
    setPreviewLoading(true)
    const localTaskId = addTask({
      jobType: 'voice-preview',
      sourceName: detail?.name || selectedId,
      sourcePath: selectedId,
      params: { profile_id: selectedId, text, speed: 1.0, language: previewLanguage },
    })
    updateTask(localTaskId, { message: '正在创建音色试听任务' })
    try {
      const remote = await voiceApi.preview(selectedId, {
        text,
        speed: 1.0,
        language: previewLanguage,
      })
      updateTask(localTaskId, {
        serverTaskId: remote.task_id,
        status: remote.state as TaskStatus,
        stage: remote.stage ?? undefined,
        progress: Math.round(remote.progress * 100),
        message: remote.message || '后端已接管音色试听任务',
        detail: remote.detail,
      })
      setPage('task-center')
    } catch (error) {
      updateTask(localTaskId, { status: 'failed', message: '音色试听任务创建失败', errorMessage: String(error) })
      setActionError(`试听生成失败：${errorMessage(error)}`)
    } finally {
      setPreviewLoading(false)
    }
  }, [addTask, detail?.name, previewLanguage, previewText, selectedId, setPage, updateTask])

  const handleDesign = useCallback(async () => {
    const name = designName.trim()
    const description = designDesc.trim()
    const refText = designRefText.trim()
    if (!name || !description) return
    setActionError('')
    setDesigning(true)
    const localTaskId = addTask({
      jobType: 'voice-design',
      sourceName: name,
      sourcePath: '',
      params: { name, description, ref_text: refText || undefined },
    })
    updateTask(localTaskId, { message: '正在创建音色设计任务' })
    try {
      const remote = await voiceApi.design({ name, description, ref_text: refText || undefined })
      updateTask(localTaskId, {
        serverTaskId: remote.task_id,
        status: remote.state as TaskStatus,
        stage: remote.stage ?? undefined,
        progress: Math.round(remote.progress * 100),
        message: remote.message || '后端已接管音色设计任务',
        detail: remote.detail,
      })
      setPage('task-center')
    } catch (error) {
      updateTask(localTaskId, { status: 'failed', message: '音色设计任务创建失败', errorMessage: String(error) })
      setActionError(`音色设计失败：${errorMessage(error)}`)
    } finally {
      setDesigning(false)
    }
  }, [addTask, designName, designDesc, designRefText, setPage, updateTask])

  const handleAnalyze = useCallback(async () => {
    if (!cloneAudioPath) return
    const requestId = ++analysisRequestId.current
    setActionError('')
    setAnalysisId('')
    setSourceFingerprint('')
    setCandidates([])
    setRecommendedCandidateId(null)
    setSelectedCandidateId(null)
    setCloneRefText('')
    setAnalysisWarnings([])
    setAnalyzing(true)
    try {
      const res = await voiceApi.analyzeSegments({
        audio_path: cloneAudioPath,
        subtitle_path: cloneSubtitlePath || undefined,
        audio_language: cloneAudioLanguage,
        separate_vocals: separateVocals,
        x_vector_only_mode: cloneMode === 'x-vector',
      })
      if (requestId !== analysisRequestId.current) return
      const nextCandidates = res.candidates ?? []
      const recommendedId = nextCandidates.some((candidate) => candidate.eligible && candidate.candidate_id === res.recommended_candidate_id)
        ? res.recommended_candidate_id ?? null
        : null
      const recommendedCandidate = recommendedId
        ? nextCandidates.find((candidate) => candidate.candidate_id === recommendedId) ?? null
        : null
      setAnalysisId(res.analysis_id ?? '')
      setSourceFingerprint(res.source_fingerprint ?? '')
      setCandidates(nextCandidates)
      setRecommendedCandidateId(recommendedId)
      setSelectedCandidateId(recommendedId)
      setCloneRefText(recommendedCandidate?.text ?? '')
      setAnalysisWarnings(res.warnings ?? [])
    } catch (error) {
      if (requestId !== analysisRequestId.current) return
      setActionError(`音频分析失败：${errorMessage(error)}`)
    } finally {
      if (requestId === analysisRequestId.current) setAnalyzing(false)
    }
  }, [cloneAudioLanguage, cloneAudioPath, cloneMode, cloneSubtitlePath, separateVocals])

  const handleSelectCandidate = useCallback((candidate: VoiceCloneCandidate) => {
    if (!candidate.eligible) {
      setActionError('该候选未通过克隆质量门槛，可试听核对但不能用于克隆')
      return
    }
    setSelectedCandidateId(candidate.candidate_id)
    setCloneRefText(candidate.text)
    setActionError('')
  }, [])

  const handlePreviewCandidate = useCallback((candidate: VoiceCloneCandidate) => {
    const previewPath = candidate.preview_audio_path || cloneAudioPath
    if (!previewPath) return
    showAudio(previewPath, `克隆候选 · ${candidateSourceLabel(candidate.source_variant)} · ${candidate.start.toFixed(1)}-${candidate.end.toFixed(1)}s`)
    if (!candidate.preview_audio_path) seekAudio(candidate.start)
    if (!useAudioPlayerStore.getState().isPlaying) {
      useAudioPlayerStore.getState().togglePlay()
    }
  }, [cloneAudioPath, seekAudio, showAudio])

  const handleClone = useCallback(async () => {
    const name = cloneName.trim()
    if (!cloneAudioPath || !name) return
    const selectedCandidate = candidates.find((candidate) => candidate.candidate_id === selectedCandidateId)
    if (!analysisId || !selectedCandidate) {
      setActionError('请先完成素材分析并选择一个候选片段')
      return
    }
    if (!selectedCandidate.eligible) {
      setActionError('所选候选未通过克隆质量门槛，请重新分析并选择合格片段')
      return
    }
    const xVectorOnly = cloneMode === 'x-vector'
    const refText = cloneRefText.trim()
    if (!xVectorOnly && !refText) {
      setActionError('高保真 ICL 模式需要确认与候选片段完全一致的文本')
      return
    }
    const confirmedText = xVectorOnly ? '' : refText
    setActionError('')
    setCloning(true)
    const cloneParams = {
      audio_path: cloneAudioPath,
      name,
      ref_text: xVectorOnly ? undefined : (refText || undefined),
      x_vector_only_mode: xVectorOnly,
      analysis_id: analysisId,
      candidate_id: selectedCandidate.candidate_id,
      confirmed_text: confirmedText,
    }
    const localTaskId = addTask({
      jobType: 'voice-clone',
      sourceName: name,
      sourcePath: cloneAudioPath,
      params: cloneParams,
    })
    updateTask(localTaskId, { message: '正在创建音色克隆任务' })
    try {
      const remote = await voiceApi.clone(cloneParams)
      updateTask(localTaskId, {
        serverTaskId: remote.task_id,
        status: remote.state as TaskStatus,
        stage: remote.stage ?? undefined,
        progress: Math.round(remote.progress * 100),
        message: remote.message || '后端已接管音色克隆任务',
        detail: remote.detail,
      })
      setPage('task-center')
    } catch (error) {
      updateTask(localTaskId, { status: 'failed', message: '音色克隆任务创建失败', errorMessage: String(error) })
      setActionError(`音色克隆失败：${errorMessage(error)}`)
    } finally {
      setCloning(false)
    }
  }, [addTask, analysisId, candidates, cloneAudioPath, cloneMode, cloneName, cloneRefText, selectedCandidateId, setPage, updateTask])

  const handleDelete = useCallback(async () => {
    if (!selectedId || detail?.id !== selectedId) {
      setActionError('当前音色详情尚未加载完成，请重新选择后再删除')
      return
    }
    const profileId = selectedId
    const requestId = ++selectionRequestId.current
    setActionError('')
    try {
      await voiceApi.deleteProfile(profileId)
      const selectionIsCurrent = requestId === selectionRequestId.current
      if (selectionIsCurrent) {
        setSelectedId(null)
        setDetail(null)
        setPanel('empty')
      }
      await loadProfiles(selectionIsCurrent)
    } catch (error) {
      if (requestId !== selectionRequestId.current) return
      setActionError(`删除音色失败：${errorMessage(error)}`)
    }
  }, [detail?.id, selectedId, loadProfiles])

  const handleSelectCloneAudio = useCallback(async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.audio],
      browserPrompt: '请输入参考音频所在目录的完整路径：',
    })
    if (files.length > 0) {
      invalidateAnalysis()
      setCloneAudioPath(files[0]!)
      setCloneSubtitlePath('')
      setActionError('')
    }
  }, [invalidateAnalysis, selectFiles])

  const handleSelectCloneSubtitle = useCallback(async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.subtitle],
      browserPrompt: '请输入参考字幕文件的完整路径：',
    })
    if (files.length > 0) {
      invalidateAnalysis()
      setCloneSubtitlePath(files[0]!)
      setActionError('')
    }
  }, [invalidateAnalysis, selectFiles])

  const showCreate = (type: 'design' | 'clone') => {
    selectionRequestId.current += 1
    setSelectedId(null)
    setDetail(null)
    setActionError('')
    invalidateAnalysis()
    if (type === 'design') {
      setDesignName(''); setDesignDesc(''); setDesignRefText('')
      setPanel('design-create')
    } else {
      setCloneName(''); setCloneRefText(''); setCloneAudioPath(''); setCloneSubtitlePath(''); setCloneAudioLanguage('ja'); setCloneMode('icl'); setSeparateVocals(false)
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
    <div className="voice-lab-detail-field" style={opts?.full ? { gridColumn: '1 / -1' } : undefined}>
      <div style={S.label}>{label}</div>
      <div className="voice-lab-detail-value" style={opts?.mono ? S.valueMono : opts?.muted ? S.valueMuted : S.value}>{value}</div>
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
              <div className="voice-lab-panel-header" style={S.panelHeader}>
                音色详情
                <span style={S.panelSubtitle}>— Qwen3 CustomVoice 预设</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('preset')}>预设</span></div>
              </div>
              <div style={S.panelBody}>
                <div className="voice-lab-detail-grid" style={S.detailGrid}>
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
              <div className="voice-lab-panel-header" style={S.panelHeader}>语气控制 (Instruct)</div>
              <div style={S.panelBody}>
                <div className="voice-lab-form-grid" style={S.formGrid}>
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
                <div className="voice-lab-actions-row" style={S.actionsRow}>
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
            <div className="voice-lab-panel-header" style={S.panelHeader}>
              音色设计
              <span style={S.panelSubtitle}>— 自然语言描述生成新音色</span>
              <div style={{ marginLeft: 'auto' }}><span style={S.tag('design')}>VoiceDesign</span></div>
            </div>
            <div style={S.panelBody}>
              <div className="voice-lab-form-grid" style={S.formGrid}>
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
              <div className="voice-lab-actions-row" style={S.actionsRow}>
                <button style={S.btnPrimarySm} onClick={handleDesign} disabled={designing || !designName.trim() || !designDesc.trim()}>
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
              <div className="voice-lab-panel-header" style={S.panelHeader}>
                设计音色详情
                <span style={S.panelSubtitle}>— VoiceDesign 生成</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('design')}>VoiceDesign</span></div>
              </div>
              <div style={S.panelBody}>
                <div className="voice-lab-detail-grid" style={S.detailGrid}>
                  {renderDetailField('名称', detail.name)}
                  {renderDetailField('ID', detail.id, { mono: true })}
                  {renderDetailField('状态', detail.available ? '已生成' : '待生成')}
                  {renderDetailField('引擎', 'qwen3_design')}
                  {renderDetailField('音色描述', detail.design_instruct || detail.description || '—', { muted: true, full: true })}
                  {renderDetailField('参考音频', detail.ref_audio || '—', { mono: true, full: true })}
                </div>
                <div className="voice-lab-actions-row" style={S.actionsRow}>
                  <button style={S.btnSm} onClick={() => showCreate('design')}>重新生成</button>
                  <button style={S.btnDanger} onClick={handleDelete}>删除音色</button>
                </div>
              </div>
            </div>
            {renderPreviewPanel()}
          </>
        )

      case 'clone-create':
        return (
          <div style={S.panel}>
            <div className="voice-lab-panel-header" style={S.panelHeader}>
              音色克隆
              <span style={S.panelSubtitle}>— 从参考音频提取音色特征</span>
              <div style={{ marginLeft: 'auto' }}><span style={S.tag('clone')}>Clone</span></div>
            </div>
            <div style={S.panelBody}>
              <div className="voice-lab-form-grid" style={S.formGrid}>
                <div style={S.formField}>
                  <label style={S.formLabel}>配置名称 *</label>
                  <input style={S.input} type="text" value={cloneName} onChange={e => setCloneName(e.target.value)} placeholder="克隆音色名称" />
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>克隆模式</label>
                  <select
                    style={S.input}
                    value={cloneMode}
                    onChange={event => {
                      invalidateAnalysis()
                      setActionError('')
                      setCloneMode(event.target.value as CloneMode)
                    }}
                  >
                    <option value="icl">高保真 ICL</option>
                    <option value="x-vector">仅说话人向量 (x-vector)</option>
                  </select>
                  <span style={S.hint}>
                    {cloneMode === 'icl'
                      ? '结合语音与准确文本，音色还原更好'
                      : '无可靠逐字文本时的降级模式；只提取说话人特征，还原度通常较低，跨语言并不要求使用此模式'}
                  </span>
                </div>
                <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                  <label style={S.formLabel}>
                    候选确认文本 {cloneMode === 'icl' ? '*' : '(x-vector 模式不使用)'}
                  </label>
                  <input
                    style={{ ...S.input, background: cloneMode === 'x-vector' || !selectedCandidateId ? 'var(--bg)' : 'var(--surface)' }}
                    type="text"
                    value={cloneRefText}
                    onChange={event => setCloneRefText(event.target.value)}
                    placeholder={selectedCandidateId ? '请逐字确认候选片段中实际说出的内容' : '分析并选择候选片段后自动填入'}
                    disabled={cloneMode === 'x-vector' || !selectedCandidateId}
                  />
                  <span style={S.hint}>
                    {cloneMode === 'icl'
                      ? '选择候选后会自动填入识别文本；请在提交前修正为与片段完全一致的内容。'
                      : 'x-vector 仅使用说话人特征，确认文本不可编辑。'}
                  </span>
                </div>
                <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                  <label style={S.formLabel}>参考音频 *</label>
                  <button
                    type="button"
                    className="voice-lab-upload-zone"
                    style={{ ...S.uploadZone, width: '100%', background: 'var(--surface)', fontFamily: 'var(--font-body)' }}
                    onClick={handleSelectCloneAudio}
                    aria-label="选择参考音频"
                  >
                    <UploadIcon />
                    <div>{cloneAudioPath || '点击选择参考音频文件 (.wav / .mp3)'}</div>
                    <div style={{ fontSize: 11, marginTop: 4 }}>可选择包含多句的音频；分析后从切分候选中选择克隆片段</div>
                  </button>
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>参考字幕</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button style={S.btnSm} type="button" onClick={handleSelectCloneSubtitle}>
                      {cloneSubtitlePath ? '更换字幕' : '选择字幕'}
                    </button>
                    {cloneSubtitlePath && (
                      <button
                        style={S.btnSm}
                        type="button"
                        onClick={() => {
                          invalidateAnalysis()
                          setCloneSubtitlePath('')
                          setActionError('')
                        }}
                      >
                        移除字幕
                      </button>
                    )}
                  </div>
                  <span style={S.hint}>{cloneSubtitlePath || '未提供时使用 ASR 识别音频文本'}</span>
                </div>
                <div style={S.formField}>
                  <label style={S.formLabel}>参考音频语言</label>
                  <select
                    style={S.input}
                    value={cloneAudioLanguage}
                    onChange={event => {
                      invalidateAnalysis()
                      setActionError('')
                      setCloneAudioLanguage(event.target.value)
                    }}
                  >
                    <option value="ja">日语</option>
                    <option value="zh">中文</option>
                    <option value="en">英语</option>
                  </select>
                </div>
                <div style={{ ...S.formField, gridColumn: '1 / -1' }}>
                  <label style={{ ...S.formLabel, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={separateVocals}
                      onChange={event => {
                        invalidateAnalysis()
                        setActionError('')
                        setSeparateVocals(event.target.checked)
                      }}
                    />
                    分析前分离人声
                  </label>
                  <span style={S.hint}>默认关闭。仅在背景音乐明显时启用；候选会标明使用原始音频还是分离人声。</span>
                </div>
              </div>

              {/* Segment analysis */}
              {candidates.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      克隆候选片段
                    </div>
                    {sourceFingerprint && (
                      <span style={{ ...S.hint, marginLeft: 'auto', fontFamily: 'var(--font-mono)' }}>
                        素材指纹 {sourceFingerprint.replace(/^sha256:/, '').slice(0, 12)}
                      </span>
                    )}
                  </div>
                  <div className="voice-lab-table-scroll">
                    <table style={S.segmentTable}>
                      <thead>
                        <tr>
                          <th style={S.segTh}>选择</th>
                          <th style={S.segTh}>时间</th>
                          <th style={S.segTh}>来源</th>
                          <th style={S.segTh}>文本 / 评分详情</th>
                          <th style={S.segTh}>评分</th>
                          <th style={S.segTh}>状态</th>
                          <th style={S.segTh}>试听</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.map((candidate) => {
                          const isRecommended = candidate.candidate_id === recommendedCandidateId
                          const isSelected = candidate.candidate_id === selectedCandidateId
                          const isEligible = candidate.eligible
                          const detailsText = candidateDetails(candidate.details)
                          return (
                            <tr
                              key={candidate.candidate_id}
                              onClick={() => {
                                if (isEligible) handleSelectCandidate(candidate)
                              }}
                              style={{
                                cursor: isEligible ? 'pointer' : 'default',
                                opacity: isEligible ? 1 : 0.68,
                                background: isSelected
                                  ? 'oklch(95% 0.025 255)'
                                  : isRecommended
                                    ? 'oklch(97% 0.01 145)'
                                    : undefined,
                              }}
                            >
                              <td style={S.segTd}>
                                <input
                                  type="radio"
                                  name="voice-clone-candidate"
                                  checked={isSelected}
                                  onChange={() => handleSelectCandidate(candidate)}
                                  disabled={!isEligible}
                                  aria-label={`选择 ${candidate.start.toFixed(1)} 到 ${candidate.end.toFixed(1)} 秒的候选片段`}
                                />
                              </td>
                              <td style={{ ...S.segTd, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                                {candidate.start.toFixed(1)} – {candidate.end.toFixed(1)}s
                              </td>
                              <td style={{ ...S.segTd, whiteSpace: 'nowrap' }}>{candidateSourceLabel(candidate.source_variant)}</td>
                              <td style={{ ...S.segTd, minWidth: 260 }}>
                                <div>{candidate.text || '（无识别文本）'}</div>
                                {detailsText && <div style={{ ...S.hint, marginTop: 4 }}>{detailsText}</div>}
                                {candidate.reasons.length > 0 && (
                                  <div style={{ fontSize: 11, color: 'var(--warning)', marginTop: 4 }}>
                                    {candidate.reasons.join('；')}
                                  </div>
                                )}
                              </td>
                              <td style={S.segTd}>
                                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 11, color: candidate.score >= 80 ? 'var(--success)' : 'var(--warning)' }}>
                                  {candidate.score}
                                </span>
                              </td>
                              <td style={{ ...S.segTd, whiteSpace: 'nowrap' }}>
                                {isRecommended && <span style={S.tag('ready')}>推荐</span>}
                                {!isEligible && <span style={S.tag('unavail')}>不合格</span>}
                                {isEligible && !isRecommended && (candidate.label || '—')}
                              </td>
                              <td style={S.segTd}>
                                <button
                                  style={S.btnSm}
                                  type="button"
                                  onClick={event => {
                                    event.stopPropagation()
                                    handlePreviewCandidate(candidate)
                                  }}
                                >
                                  <PlayIcon /> 试听
                                </button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {analysisWarnings.length > 0 && (
                <div style={{ ...S.hint, marginTop: 8, color: 'var(--warning)' }}>
                  {analysisWarnings.join('；')}
                </div>
              )}

              {analysisId && candidates.length === 0 && (
                <div style={{ ...S.hint, marginTop: 12 }}>分析完成，但没有可用于克隆的候选片段。</div>
              )}

              {analysisId && candidates.length > 0 && !candidates.some((candidate) => candidate.eligible) && (
                <div style={{ ...S.hint, marginTop: 12, color: 'var(--warning)' }}>
                  当前片段均未通过质量门槛；仍可试听检查，但不能用于克隆。
                </div>
              )}

              {!analysisId && candidates.length > 0 && (
                <div style={{ ...S.hint, marginTop: 12, color: 'var(--warning)' }}>
                  当前后端返回了旧版分析结果，无法安全绑定候选片段；请升级后端后重新分析。
                </div>
              )}

              {selectedCandidateId && analysisId && (
                <div style={{ ...S.hint, marginTop: 12 }}>
                  克隆将使用当前单选候选；切换音频、字幕、语言、模式或人声分离设置后需要重新分析。
                </div>
              )}

              <div className="voice-lab-actions-row" style={S.actionsRow}>
                <button style={S.btnSm} onClick={handleAnalyze} disabled={analyzing || !cloneAudioPath}>
                  {analyzing ? '分析中...' : '分析并生成候选'}
                </button>
                <button
                  style={S.btnPrimarySm}
                  onClick={handleClone}
                  disabled={cloning || !cloneName.trim() || !cloneAudioPath || !analysisId || !candidates.some((candidate) => candidate.candidate_id === selectedCandidateId && candidate.eligible) || (cloneMode === 'icl' && !cloneRefText.trim())}
                >
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
              <div className="voice-lab-panel-header" style={S.panelHeader}>
                克隆音色详情
                <span style={S.panelSubtitle}>— 从参考音频提取</span>
                <div style={{ marginLeft: 'auto' }}><span style={S.tag('clone')}>Clone</span></div>
              </div>
              <div style={S.panelBody}>
                <div className="voice-lab-detail-grid" style={S.detailGrid}>
                  {renderDetailField('名称', detail.name)}
                  {renderDetailField('ID', detail.id, { mono: true })}
                  {renderDetailField('状态', detail.available ? '已缓存' : '未缓存')}
                  {renderDetailField('引擎', 'qwen3_clone')}
                  {renderDetailField('参考音频', detail.ref_audio || '—', { mono: true, full: true })}
                  {renderDetailField('描述', detail.description || '—', { muted: true, full: true })}
                </div>
                <div className="voice-lab-actions-row" style={S.actionsRow}>
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
            <div>选择一个音色查看详情，或从上方设计、克隆新音色</div>
          </div>
        )
    }
  }

  const renderPreviewPanel = () => (
    <div style={S.panel}>
      <div className="voice-lab-panel-header" style={S.panelHeader}>试听</div>
      <div className="voice-lab-preview-bar" style={S.previewBar}>
        <input
          style={{ ...S.input, flex: 1, background: 'var(--bg)' }}
          type="text"
          value={previewText}
          onChange={e => setPreviewText(e.target.value)}
          placeholder="输入试听文本"
        />
        <select
          style={{ ...S.input, width: 132, flex: '0 0 132px' }}
          value={previewLanguage}
          onChange={event => setPreviewLanguage(event.target.value)}
          aria-label="试听目标语言"
        >
          {QWEN_LANGUAGE_OPTIONS.map(option => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <button style={S.btnPrimarySm} onClick={handlePreview} disabled={previewLoading || !previewText.trim()}>
          <PlayIcon /> {previewLoading ? '生成中...' : '试听'}
        </button>
      </div>
      <div style={{ padding: '8px 16px 12px', fontSize: 11, color: 'var(--muted)' }}>
        试听作为后台任务执行，完成后可在任务中心播放产物。
      </div>
    </div>
  )

  // ── Main render ────────────────────────────────────
  return (
    <div className="voice-lab-page" style={S.page}>
      {/* Action bar */}
      <div className="voice-lab-action-bar" style={S.actionBar}>
        <span style={S.title}>音色实验室</span>
        {actionError && (
          <span className="voice-lab-action-error" style={{ color: 'var(--danger)', fontSize: 12 }} title={actionError}>
            {actionError}
          </span>
        )}
        <span style={S.gpuPill}>Qwen3 扩展</span>
        <div className="voice-lab-action-spacer" style={S.spacer} />
        <button style={S.btn} onClick={() => showCreate('design')}>
          <PlusIcon /> 设计音色
        </button>
        <button style={S.btnPrimary} onClick={() => showCreate('clone')}>
          <PlusIcon /> 克隆音色
        </button>
      </div>

      {/* Content: list + work panel */}
      <div className="voice-lab-content" style={S.content}>
        {/* Profile list */}
        <div className="voice-lab-list" style={S.list}>
          <div style={S.listHeader}>
            <span>音色列表</span>
            <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}>{totalCount} 个</span>
          </div>

          {/* Filter tabs */}
          <div className="voice-lab-filter-bar" style={S.filterBar}>
            {renderFilterTab('all', '全部')}
            {renderFilterTab('preset', '预设')}
            {renderFilterTab('design', '设计')}
            {renderFilterTab('clone', '克隆')}
          </div>

          {/* Model groups */}
          <div className="voice-lab-groups">
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
                          {group.engine === 'qwen3_custom'
                            ? '暂无预设音色'
                            : `暂无${group.label}，点击「${group.engine === 'qwen3_design' ? '设计音色' : '克隆音色'}」创建`}
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
        </div>

        {/* Work panel */}
        <div className="voice-lab-work-panel" style={S.workPanel}>
          {renderPanel()}
        </div>
      </div>

      <style>{`
        .voice-lab-page,
        .voice-lab-content,
        .voice-lab-work-panel,
        .voice-lab-detail-grid,
        .voice-lab-detail-field,
        .voice-lab-form-grid,
        .voice-lab-form-grid > * {
          min-width: 0;
        }

        .voice-lab-action-error,
        .voice-lab-detail-value,
        .voice-lab-upload-zone,
        .voice-lab-work-panel {
          overflow-wrap: anywhere;
          word-break: break-word;
        }

        .voice-lab-table-scroll {
          max-width: 100%;
          overflow-x: auto;
        }

        .voice-lab-table-scroll > table {
          min-width: 620px;
        }

        @media (max-width: 1100px) {
          .voice-lab-content {
            grid-template-columns: minmax(0, 1fr) !important;
            grid-template-rows: auto minmax(0, 1fr);
            min-height: 0;
          }

          .voice-lab-list {
            max-height: 260px;
            overflow: hidden !important;
            border-right: 0 !important;
            border-bottom: 1px solid var(--border);
          }

          .voice-lab-groups {
            display: flex;
            flex: 1;
            min-height: 0;
            overflow: auto;
          }

          .voice-lab-groups > div {
            flex: 0 0 240px;
            border-right: 1px solid var(--border);
          }
        }

        @media (max-width: 760px) {
          .voice-lab-action-bar {
            align-items: flex-start !important;
            flex-wrap: wrap;
            padding: 12px 16px !important;
          }

          .voice-lab-action-error {
            flex: 1 0 100%;
            order: 3;
          }

          .voice-lab-action-spacer {
            display: none;
          }

          .voice-lab-action-bar > button {
            margin-left: auto;
          }

          .voice-lab-list {
            max-height: 220px;
          }

          .voice-lab-filter-bar {
            overflow-x: auto;
          }

          .voice-lab-filter-bar > button {
            flex: 0 0 auto;
          }

          .voice-lab-work-panel {
            padding: 16px !important;
          }

          .voice-lab-panel-header {
            align-items: flex-start !important;
            flex-wrap: wrap;
          }

          .voice-lab-detail-grid,
          .voice-lab-form-grid {
            grid-template-columns: minmax(0, 1fr) !important;
          }

          .voice-lab-form-grid > *,
          .voice-lab-detail-field {
            grid-column: 1 !important;
          }

          .voice-lab-actions-row {
            align-items: stretch !important;
            flex-wrap: wrap;
          }

          .voice-lab-actions-row > button {
            flex: 1 1 auto;
            justify-content: center;
          }

          .voice-lab-preview-bar {
            align-items: stretch !important;
            flex-direction: column;
          }

          .voice-lab-preview-bar > button {
            justify-content: center;
            width: 100%;
          }
        }
      `}</style>
    </div>
  )
}
