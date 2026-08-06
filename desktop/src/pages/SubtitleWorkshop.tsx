import { useState } from 'react'
import { subtitlesApi } from '@/api/subtitles'
import { toolsApi } from '@/api/tools'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import type { TaskStatus } from '@/stores/taskStore'
import type {
  SubtitleSegmentModel,
  ScriptToVttRequest,
} from '@/api/types'

// ── Tab types ────────────────────────────────────────────
type WorkspaceTab = 'editor' | 'translate' | 'script'

// ── Script-to-VTT modes ──────────────────────────────────
type ScriptMode = 'text_only' | 'full' | 'existing_vtt'

// ── Styles ───────────────────────────────────────────────
const S = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100%',
    overflow: 'hidden',
  },

  // Sub navigation
  subNav: {
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    alignItems: 'center',
    padding: '0 24px',
    gap: 0,
    height: 40,
    flexShrink: 0,
  },
  subNavItem: (active: boolean) => ({
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 500,
    color: active ? 'var(--accent)' : 'var(--muted)',
    cursor: 'pointer' as const,
    borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
    transition: 'color 0.12s, border-color 0.12s',
    whiteSpace: 'nowrap' as const,
  }),

  // Workspace base
  workspace: (active: boolean) => ({
    display: active ? 'flex' : 'none',
    flexDirection: 'column' as const,
    flex: 1,
    overflow: 'hidden',
  }),
  editorWorkspace: (active: boolean) => ({
    display: active ? 'grid' : 'none',
    gridTemplateRows: 'auto 1fr',
    overflow: 'hidden',
  }),

  // Toolbar
  toolbar: {
    background: 'var(--surface)',
    borderBottom: '1px solid var(--border)',
    padding: '10px 24px',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  toolbarTitle: {
    fontFamily: 'var(--font-display)',
    fontSize: 14,
    fontWeight: 600,
    letterSpacing: '-0.01em',
    marginRight: 8,
  },
  toolbarSpacer: { flex: 1 },
  fileBadge: {
    fontSize: 12,
    color: 'var(--muted)',
    padding: '4px 10px',
    background: 'var(--bg)',
    borderRadius: 12,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  fileDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: 'var(--success)',
  },

  // Buttons
  btn: {
    fontFamily: 'var(--font-body)',
    fontSize: 13,
    fontWeight: 500,
    padding: '7px 14px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--surface)',
    color: 'var(--fg)',
    cursor: 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    transition: 'background 0.12s',
  },
  btnPrimary: {
    background: 'var(--accent)',
    color: 'white',
    borderColor: 'var(--accent)',
  },
  btnSm: {
    fontSize: 12,
    padding: '5px 10px',
  },
  btnDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed' as const,
  },

  // Editor content
  editorContent: {
    display: 'grid',
    gridTemplateColumns: '1fr 260px',
    overflow: 'hidden',
  },
  editorTable: {
    overflowY: 'auto' as const,
    padding: '16px 24px',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '50px 80px 1fr 1fr 60px',
    gap: 8,
    padding: '8px 12px',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
    borderBottom: '1px solid var(--border)',
    position: 'sticky' as const,
    top: 0,
    background: 'var(--bg)',
    zIndex: 1,
  },
  segmentRow: (active: boolean, modified: boolean) => ({
    display: 'grid',
    gridTemplateColumns: '50px 80px 1fr 1fr 60px',
    gap: 8,
    padding: '8px 12px',
    borderRadius: 6,
    alignItems: 'start',
    border: modified ? '1px solid var(--warning)' : active ? '1px solid oklch(90% 0.04 255)' : '1px solid transparent',
    background: active ? 'oklch(97% 0.01 255)' : 'transparent',
    borderLeft: modified ? '3px solid var(--warning)' : undefined,
    transition: 'background 0.1s, border-color 0.1s',
  }),
  segIdx: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    color: 'var(--muted)',
    paddingTop: 4,
    textAlign: 'center' as const,
  },
  segTime: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    color: 'var(--muted)',
    paddingTop: 4,
    lineHeight: 1.5,
  },
  segCell: {
    fontSize: 13,
    lineHeight: 1.6,
    padding: '4px 8px',
    borderRadius: 4,
    border: '1px solid transparent',
    minHeight: 28,
    outline: 'none',
    transition: 'border-color 0.12s, background 0.12s',
    color: 'var(--fg)',
  },
  segCellTranslated: {
    color: 'oklch(35% 0.02 255)',
    background: 'oklch(98% 0.003 240)',
  },
  segCellEmpty: {
    color: 'var(--muted)',
    fontStyle: 'italic' as const,
  },
  segActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    paddingTop: 4,
  },
  segActionBtn: {
    width: 24,
    height: 24,
    border: 'none',
    background: 'none',
    color: 'var(--muted)',
    cursor: 'pointer',
    borderRadius: 4,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'background 0.12s, color 0.12s',
  },

  // Empty state
  editorEmpty: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    gap: 16,
    color: 'var(--muted)',
    padding: 40,
  },

  // Sidebar
  editorSidebar: {
    background: 'var(--surface)',
    borderLeft: '1px solid var(--border)',
    padding: 16,
    overflowY: 'auto' as const,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 20,
  },
  sidebarSectionTitle: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--muted)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 10,
  },
  infoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    padding: '4px 0',
  },
  infoLabel: { color: 'var(--muted)' },
  infoValue: { fontWeight: 500 },

  // Translate / Script workspace
  scrollWorkspace: {
    padding: 24,
    overflowY: 'auto' as const,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 24,
    flex: 1,
  },
  twoColLayout: {
    display: 'grid',
    gridTemplateColumns: '1fr 320px',
    gap: 24,
    alignItems: 'start',
  },

  // Panel
  panel: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    overflow: 'hidden',
  },
  panelHeader: {
    padding: '14px 16px',
    borderBottom: '1px solid var(--border)',
    fontSize: 13,
    fontWeight: 600,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  panelBody: { padding: 16 },

  // Form
  formGrid: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 14,
  },
  formField: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
  },
  formLabel: {
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--muted)',
  },
  formInput: {
    fontFamily: 'var(--font-body)',
    fontSize: 13,
    padding: '8px 12px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--surface)',
    color: 'var(--fg)',
    width: '100%',
    outline: 'none',
    transition: 'border-color 0.12s',
  },
  formHint: {
    fontSize: 11,
    color: 'var(--muted)',
    marginTop: 4,
  },
  fileInput: {
    display: 'flex',
    gap: 8,
  },
  checkboxField: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13,
  },
  twoColForm: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 12,
  },

  // Mode selector
  modeSelector: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 12,
    marginBottom: 8,
  },
  modeCard: (active: boolean) => ({
    background: 'var(--surface)',
    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
    borderRadius: 8,
    padding: 16,
    cursor: 'pointer' as const,
    transition: 'border-color 0.12s, background 0.12s',
    background2: active ? 'oklch(98% 0.005 255)' : 'transparent',
  }),
  modeCardIcon: (active: boolean) => ({
    width: 36,
    height: 36,
    borderRadius: 8,
    background: active ? 'oklch(95% 0.02 255)' : 'var(--bg)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 10,
    color: active ? 'var(--accent)' : 'var(--muted)',
  }),
  modeCardTitle: (active: boolean) => ({
    fontSize: 13,
    fontWeight: 600,
    marginBottom: 4,
    color: active ? 'var(--accent)' : 'var(--fg)',
  }),
  modeCardDesc: {
    fontSize: 11,
    color: 'var(--muted)',
    lineHeight: 1.4,
  },

  // Result
  resultGrid: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
  },
  resultRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    padding: '2px 0',
  },
  resultLabel: { color: 'var(--muted)' },
  resultValue: { fontWeight: 500 },

  // VTT preview
  vttPreview: {
    background: 'var(--fg)',
    color: 'oklch(90% 0.005 250)',
    borderRadius: 8,
    padding: 16,
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    lineHeight: 1.6,
    maxHeight: 300,
    overflowY: 'auto' as const,
  },

  // Player bar
  playerBar: {
    background: 'var(--surface)',
    borderTop: '1px solid var(--border)',
    padding: '10px 24px',
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    height: 56,
    flexShrink: 0,
  },
  playerControls: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  playerBtn: {
    width: 32,
    height: 32,
    borderRadius: '50%',
    border: '1px solid var(--border)',
    background: 'var(--surface)',
    color: 'var(--fg)',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'background 0.12s',
  },
  playerBtnPlay: {
    background: 'var(--accent)',
    color: 'white',
    borderColor: 'var(--accent)',
  },
  waveform: {
    flex: 1,
    height: 32,
    background: 'var(--bg)',
    borderRadius: 4,
    position: 'relative' as const,
    overflow: 'hidden',
  },
  waveformProgress: (pct: number) => ({
    position: 'absolute' as const,
    left: 0,
    top: 0,
    bottom: 0,
    width: `${pct}%`,
    background: 'oklch(95% 0.03 255)',
    borderRight: '2px solid var(--accent)',
  }),
  waveformBars: {
    display: 'flex',
    alignItems: 'center',
    height: '100%',
    gap: 1,
    padding: '0 4px',
  },
  waveformBar: (h: number) => ({
    flex: 1,
    background: 'oklch(85% 0.01 250)',
    borderRadius: 1,
    minWidth: 2,
    height: `${h}%`,
  }),
  playerTime: {
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    color: 'var(--muted)',
    minWidth: 80,
    textAlign: 'center' as const,
  },
  playerTrackName: {
    fontSize: 12,
    fontWeight: 500,
    maxWidth: 160,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis' as const,
  },

  // Help text
  helpText: {
    fontSize: 12,
    color: 'var(--muted)',
    lineHeight: 1.6,
  },
} as const

// ── Helpers ──────────────────────────────────────────────
function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ── SVG Icons (inline) ──────────────────────────────────
const Icon = {
  Download: () => (
    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 14 14">
      <path d="M2 10v3h10v-3M7 2v7M4 6l3 3 3-3" />
    </svg>
  ),
  Play: () => (
    <svg width="12" height="12" fill="currentColor" viewBox="0 0 12 12">
      <path d="M3 1l8 5-8 5V1z" />
    </svg>
  ),
  Delete: () => (
    <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 12 12">
      <path d="M3 3l6 6M9 3l-6 6" />
    </svg>
  ),
  Arrow: () => (
    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 14 14">
      <path d="M2 7h10M8 3l4 4-4 4" />
    </svg>
  ),
  Start: () => (
    <svg width="14" height="14" fill="currentColor" viewBox="0 0 14 14">
      <path d="M4 2l9 5-9 5V2z" />
    </svg>
  ),
  Prev: () => (
    <svg width="14" height="14" fill="currentColor" viewBox="0 0 14 14">
      <path d="M12 3L5 7l7 4V3zM3 3h2v8H3" />
    </svg>
  ),
  Next: () => (
    <svg width="14" height="14" fill="currentColor" viewBox="0 0 14 14">
      <path d="M2 3l7 4-7 4V3zM11 3h2v8h-2" />
    </svg>
  ),
  Check: () => (
    <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 16 16">
      <path d="M3 8l4 4 6-8" />
    </svg>
  ),
  Info: () => (
    <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="6" /><path d="M8 5v3M8 10v.5" />
    </svg>
  ),
  File: () => (
    <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 16 16">
      <path d="M4 2h5l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z" /><path d="M9 2v4h4" />
    </svg>
  ),
  Audio: () => (
    <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 20 20">
      <path d="M3 10V6a1 1 0 011-1h3l3-3v14l-3-3H4a1 1 0 01-1-1v-1" />
      <path d="M14 7.5a3 3 0 010 5M16 6a5.5 5.5 0 010 8" />
    </svg>
  ),
  Text: () => (
    <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 20 20">
      <path d="M4 3h12M4 7h12M4 11h8M4 15h10" />
    </svg>
  ),
  Vtt: () => (
    <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 20 20">
      <path d="M4 3h12M4 7h8M4 11h10M4 15h6" /><path d="M14 9l2 2-2 2" />
    </svg>
  ),
}

// ── Component ────────────────────────────────────────────
export default function SubtitleWorkshop() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('editor')

  // Editor state
  const [segments, setSegments] = useState<SubtitleSegmentModel[]>([])
  const [translations, setTranslations] = useState<string[]>([])
  const [filePath, setFilePath] = useState('')
  const [fileName, setFileName] = useState('')
  const [exportFormat, setExportFormat] = useState('srt')
  const [modifiedIdx, setModifiedIdx] = useState<Set<number>>(new Set())
  const [activeIdx, setActiveIdx] = useState<number | null>(null)
  const { selectFiles } = useFileSelector()

  // Translate state
  const [translatePath, setTranslatePath] = useState('')
  const [translateOutput, setTranslateOutput] = useState('')
  const [translateProvider, setTranslateProvider] = useState('deepseek')
  const [translateSrcLang, setTranslateSrcLang] = useState('ja')
  const [translateTgtLang, setTranslateTgtLang] = useState('zh')
  const [translateBilingual, setTranslateBilingual] = useState(true)

  // Script-to-VTT state
  const [scriptMode, setScriptMode] = useState<ScriptMode>('text_only')
  const [scriptPath, setScriptPath] = useState('')
  const [audioPath, setAudioPath] = useState('')
  const [vttPath, setVttPath] = useState('')
  const [scriptFmt, setScriptFmt] = useState('vtt')
  const [useLlmClean, setUseLlmClean] = useState(true)
  const [asrModelSize, setAsrModelSize] = useState('large-v3')
  const [asrLanguage, setAsrLanguage] = useState('ja')
  const [trackIndex, setTrackIndex] = useState<string>('')
  const [verticalMode, setVerticalMode] = useState('auto')

  // Common loading
  const [loading, setLoading] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  // Audio player
  const audioPlayer = useAudioPlayerStore()
  const setPage = useNavStore((state) => state.setPage)
  const addTask = useTaskStore((state) => state.addTask)
  const updateTask = useTaskStore((state) => state.updateTask)

  // ── Handlers ───────────────────────────────────────────

  const handleLoadSubtitle = async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.subtitle],
      browserPrompt: '请输入字幕文件所在目录的完整路径：',
    })
    if (files.length === 0) return
    const path = files[0]!
    setFilePath(path)
    setFileName(path.split(/[/\\]/).pop() || path)
    setLoading('load')
    setError('')
    setMessage('')
    try {
      const res = await subtitlesApi.load({ file_path: path })
      setSegments(res.segments)
      setTranslations(res.segments.map(() => ''))
      setModifiedIdx(new Set())
      setMessage(`已加载 ${res.segments.length} 条字幕`)
    } catch (err) {
      setError(`加载失败: ${err}`)
    } finally {
      setLoading('')
    }
  }

  const handleExport = async () => {
    if (segments.length === 0) return
    setLoading('export')
    setError('')
    try {
      // Build segments with translations
      const exportSegments = segments.map((seg, i) => ({
        ...seg,
        text: translations[i] || seg.text,
      }))
      const outPath = filePath.replace(/\.[^.]+$/, `_export.${exportFormat}`)
      await subtitlesApi.export({
        segments: exportSegments,
        output_path: outPath,
      })
      setMessage(`已导出到: ${outPath}`)
    } catch (err) {
      setError(`导出失败: ${err}`)
    } finally {
      setLoading('')
    }
  }

  const handleNormalize = () => {
    // Normalize timestamps: ensure each segment's end <= next segment's start
    const normalized = [...segments]
    for (let i = 0; i < normalized.length - 1; i++) {
      const curr = normalized[i]!
      const next = normalized[i + 1]!
      if (curr.end > next.start) {
        normalized[i] = { ...curr, end: next.start }
      }
    }
    setSegments(normalized)
    setMessage('时间轴已规范化')
  }

  const handleSegmentEdit = (idx: number, field: 'text' | 'translated', value: string) => {
    if (field === 'text') {
      const updated = [...segments]
      updated[idx] = { ...updated[idx]!, text: value }
      setSegments(updated)
    } else {
      const updated = [...translations]
      updated[idx] = value
      setTranslations(updated)
    }
    setModifiedIdx((prev) => new Set(prev).add(idx))
  }

  const handleDeleteSegment = (idx: number) => {
    setSegments((prev) => prev.filter((_, i) => i !== idx))
    setTranslations((prev) => prev.filter((_, i) => i !== idx))
    setModifiedIdx((prev) => {
      const next = new Set<number>()
      prev.forEach((i) => { if (i < idx) next.add(i); if (i > idx) next.add(i - 1) })
      return next
    })
  }

  const handlePlaySegment = (seg: SubtitleSegmentModel) => {
    if (!audioPath) {
      setError('请先为字幕选择对应的音频文件')
      return
    }
    if (audioPlayer.src !== audioPath) {
      audioPlayer.show(audioPath, audioPath.split(/[/\\]/).pop() || '字幕伴随音频')
    }
    audioPlayer.seek(seg.start)
    if (!useAudioPlayerStore.getState().isPlaying) {
      useAudioPlayerStore.getState().togglePlay()
    }
  }

  const handleSelectAudio = async () => {
    const files = await selectFiles({
      multiple: false,
      filters: [FILE_FILTERS.audio],
      browserPrompt: '请输入音频文件所在目录的完整路径：',
    })
    if (files.length === 0) return
    setAudioPath(files[0]!)
    audioPlayer.show(files[0]!, files[0]!.split(/[/\\]/).pop() || '字幕伴随音频')
    setError('')
  }

  // ── Translate handler ──────────────────────────────────
  const handleTranslate = async () => {
    if (!translatePath) return
    setLoading('translate')
    setError('')
    const profile = {
      output_path: translateOutput || undefined,
      provider: translateProvider,
      source_lang: translateSrcLang,
      target_lang: translateTgtLang,
      bilingual: translateBilingual,
    }
    const localTaskId = addTask({
      jobType: 'translate-subtitle',
      sourceName: translatePath.split(/[/\\]/).pop() || translatePath,
      sourcePath: translatePath,
      params: { task_type: 'tool.translate_subtitle', ...profile },
    })
    updateTask(localTaskId, { message: '正在创建字幕翻译任务' })
    try {
      const remote = await toolsApi.create({
        task_type: 'tool.translate_subtitle',
        input_path: translatePath,
        execution_profile: profile,
      })
      updateTask(localTaskId, {
        serverTaskId: remote.task_id,
        status: remote.state as TaskStatus,
        stage: remote.stage ?? undefined,
        progress: Math.round(remote.progress * 100),
        message: remote.message || '后端已接管字幕翻译任务',
        detail: remote.detail,
      })
      setMessage('翻译任务已提交，可在任务中心查看进度和结果')
      setPage('task-center')
    } catch (err) {
      updateTask(localTaskId, {
        status: 'failed',
        message: '字幕翻译任务创建失败',
        errorMessage: String(err),
      })
      setError(`翻译失败: ${err}`)
    } finally {
      setLoading('')
    }
  }

  // ── Script-to-VTT handler ──────────────────────────────
  const handleScriptToVtt = async () => {
    if (!scriptPath) return
    if (scriptMode === 'full' && !audioPath) {
      setError('完整模式需要选择音频文件')
      return
    }
    if (scriptMode === 'existing_vtt' && !vttPath) {
      setError('已有字幕模式需要选择字幕文件')
      return
    }
    setLoading('script')
    setError('')
    try {
      const req: ScriptToVttRequest = {
        script_path: scriptPath,
        fmt: scriptFmt,
        use_llm_clean: useLlmClean,
      }
      if (scriptMode === 'full') {
        req.audio_path = audioPath || undefined
        req.asr_model_size = asrModelSize
        req.asr_language = asrLanguage
        req.track_index = trackIndex ? parseInt(trackIndex) : null
      }
      if (scriptMode === 'existing_vtt') {
        req.vtt_path = vttPath || undefined
      }
      req.vertical_mode = verticalMode
      const localTaskId = addTask({
        jobType: 'script-to-vtt',
        sourceName: scriptPath.split(/[/\\]/).pop() || scriptPath,
        sourcePath: scriptPath,
        params: { task_type: 'subtitle.script_to_vtt', mode: scriptMode, ...req },
      })
      updateTask(localTaskId, { message: '正在创建台本转字幕任务' })
      try {
        const remote = await subtitlesApi.createScriptTask(req)
        updateTask(localTaskId, {
          serverTaskId: remote.task_id,
          status: remote.state as TaskStatus,
          stage: remote.stage ?? undefined,
          progress: Math.round(remote.progress * 100),
          message: remote.message || '后端已接管台本转字幕任务',
          detail: remote.detail,
        })
        setMessage('台本转字幕任务已提交，可在任务中心查看进度和结果')
        setPage('task-center')
      } catch (submitError) {
        updateTask(localTaskId, {
          status: 'failed',
          message: '台本转字幕任务创建失败',
          errorMessage: String(submitError),
        })
        throw submitError
      }
    } catch (err) {
      setError(`台本转字幕失败: ${err}`)
    } finally {
      setLoading('')
    }
  }

  const switchTab = (tab: WorkspaceTab) => {
    setActiveTab(tab)
    setMessage('')
    setError('')
  }

  // ── Render ─────────────────────────────────────────────
  return (
    <div style={S.container}>
      {/* Status message */}
      {(message || error) && (
        <div style={{
          padding: '6px 24px',
          fontSize: 12,
          color: error ? 'var(--danger)' : 'var(--success)',
          background: error ? 'rgba(239,68,68,0.06)' : 'rgba(34,197,94,0.06)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          {error || message}
        </div>
      )}

      {/* Sub Navigation */}
      <nav style={S.subNav}>
        <div style={S.subNavItem(activeTab === 'editor')} onClick={() => switchTab('editor')}>
          字幕编辑
        </div>
        <div style={S.subNavItem(activeTab === 'translate')} onClick={() => switchTab('translate')}>
          翻译
        </div>
        <div style={S.subNavItem(activeTab === 'script')} onClick={() => switchTab('script')}>
          台本转字幕
        </div>
      </nav>

      {/* ── Workspace 1: Editor ─────────────────────────── */}
      <div style={S.editorWorkspace(activeTab === 'editor')}>
        {/* Toolbar */}
        <div style={S.toolbar}>
          <h2 style={S.toolbarTitle}>字幕编辑</h2>
          <button style={S.btn} onClick={handleLoadSubtitle}>
            <Icon.Download /> 加载字幕
          </button>
          <button style={S.btn} onClick={handleSelectAudio}>
            <Icon.Audio /> {audioPath ? '更换音频' : '选择音频'}
          </button>
          {fileName && (
            <span style={S.fileBadge}>
              <span style={S.fileDot} />
              {fileName} &middot; {segments.length} 条
            </span>
          )}
          <div style={S.toolbarSpacer} />
          {segments.length > 0 && (
            <>
              <button style={{ ...S.btn, ...S.btnSm }} onClick={handleNormalize}>
                规范化时间轴
              </button>
              <select
                style={{ ...S.formInput, width: 'auto', padding: '5px 8px', fontSize: 12 }}
                value={exportFormat}
                onChange={(e) => setExportFormat(e.target.value)}
              >
                <option value="srt">SRT</option>
                <option value="vtt">VTT</option>
                <option value="lrc">LRC</option>
              </select>
              <button style={{ ...S.btn, ...S.btnSm }} onClick={handleExport} disabled={!!loading}>
                导出
              </button>
            </>
          )}
        </div>

        {/* Editor content */}
        <div style={S.editorContent}>
          {/* Table */}
          <div style={S.editorTable}>
            {segments.length === 0 ? (
              <div style={S.editorEmpty}>
                <svg width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1" viewBox="0 0 48 48" style={{ opacity: 0.3 }}>
                  <rect x="8" y="12" width="32" height="24" rx="4" />
                  <path d="M16 20h16M16 26h10" />
                </svg>
                <p>点击"加载字幕"按钮选择字幕文件<br />支持 SRT、VTT、LRC 格式</p>
                <button style={{ ...S.btn, ...S.btnPrimary }} onClick={handleLoadSubtitle}>
                  <Icon.Download /> 加载字幕
                </button>
              </div>
            ) : (
              <>
                <div style={S.tableHeader}>
                  <span>#</span>
                  <span>时间轴</span>
                  <span>原文</span>
                  <span>译文</span>
                  <span>操作</span>
                </div>
                {segments.map((seg, i) => (
                  <div
                    key={i}
                    style={S.segmentRow(activeIdx === i, modifiedIdx.has(i))}
                    onClick={() => setActiveIdx(i)}
                  >
                    <div style={S.segIdx}>{i + 1}</div>
                    <div style={S.segTime}>
                      {formatTime(seg.start)}<br />{formatTime(seg.end)}
                    </div>
                    <div
                      style={S.segCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => handleSegmentEdit(i, 'text', e.currentTarget.textContent || '')}
                    >
                      {seg.text}
                    </div>
                    <div
                      style={{
                        ...S.segCell,
                        ...(translations[i] ? S.segCellTranslated : S.segCellEmpty),
                      }}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => handleSegmentEdit(i, 'translated', e.currentTarget.textContent || '')}
                    >
                      {translations[i] || '（未翻译）'}
                    </div>
                    <div style={S.segActions}>
                      <button style={S.segActionBtn} title="播放此段" onClick={() => handlePlaySegment(seg)}>
                        <Icon.Play />
                      </button>
                      <button style={S.segActionBtn} title="删除" onClick={() => handleDeleteSegment(i)}>
                        <Icon.Delete />
                      </button>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>

          {/* Sidebar */}
          <div style={S.editorSidebar}>
            <div>
              <div style={S.sidebarSectionTitle}>文件信息</div>
              <div style={S.infoRow}><span style={S.infoLabel}>文件</span><span style={S.infoValue}>{fileName || '—'}</span></div>
              <div style={S.infoRow}><span style={S.infoLabel}>格式</span><span style={S.infoValue}>{filePath ? filePath.split('.').pop()?.toUpperCase() : '—'}</span></div>
              <div style={S.infoRow}><span style={S.infoLabel}>条目数</span><span style={S.infoValue}>{segments.length}</span></div>
              {segments.length > 0 && (
                <div style={S.infoRow}>
                  <span style={S.infoLabel}>时长</span>
                  <span style={S.infoValue}>{formatDuration(segments[segments.length - 1]!.end)}</span>
                </div>
              )}
            </div>

            {segments.length > 0 && (
              <div>
                <div style={S.sidebarSectionTitle}>翻译状态</div>
                <div style={S.infoRow}>
                  <span style={S.infoLabel}>已翻译</span>
                  <span style={{ ...S.infoValue, color: 'var(--success)' }}>
                    {translations.filter((t) => t).length} / {segments.length}
                  </span>
                </div>
                <div style={S.infoRow}>
                  <span style={S.infoLabel}>未翻译</span>
                  <span style={{ ...S.infoValue, color: 'var(--warning)' }}>
                    {translations.filter((t) => !t).length}
                  </span>
                </div>
                <div style={S.infoRow}>
                  <span style={S.infoLabel}>已修改</span>
                  <span style={{ ...S.infoValue, color: 'var(--accent)' }}>{modifiedIdx.size}</span>
                </div>
                {/* Progress bar */}
                <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden', marginTop: 8 }}>
                  <div style={{
                    height: '100%',
                    background: 'var(--accent)',
                    borderRadius: 2,
                    width: `${segments.length ? (translations.filter((t) => t).length / segments.length * 100) : 0}%`,
                    transition: 'width 0.3s',
                  }} />
                </div>
              </div>
            )}

            {segments.length > 0 && (
              <div>
                <div style={S.sidebarSectionTitle}>快捷操作</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <button
                    style={{ ...S.btn, ...S.btnSm, justifyContent: 'center', width: '100%' }}
                    onClick={() => switchTab('translate')}
                  >
                    翻译未翻译条目 →
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Workspace 2: Translate ──────────────────────── */}
      <div style={S.workspace(activeTab === 'translate')}>
        <div style={S.scrollWorkspace}>
          <div style={S.twoColLayout}>
            {/* Left: config */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* File selection */}
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.File /> 输入文件
                </div>
                <div style={S.panelBody}>
                  <div style={S.formGrid}>
                    <div style={S.formField}>
                      <label style={S.formLabel}>字幕文件路径</label>
                      <div style={S.fileInput}>
                        <input
                          style={{ ...S.formInput, flex: 1 }}
                          value={translatePath}
                          onChange={(e) => setTranslatePath(e.target.value)}
                          placeholder="选择字幕文件 (.srt / .vtt / .lrc)"
                        />
                        <button
                          style={{ ...S.btn, ...S.btnSm }}
                          onClick={async () => {
                            const files = await selectFiles({
                              multiple: false,
                              filters: [FILE_FILTERS.subtitle],
                              browserPrompt: '请输入字幕文件所在目录的完整路径：',
                            })
                            if (files.length > 0) setTranslatePath(files[0]!)
                          }}
                        >
                          浏览
                        </button>
                      </div>
                      <div style={S.formHint}>支持 SRT、VTT、LRC 格式</div>
                    </div>
                    <div style={S.formField}>
                      <label style={S.formLabel}>输出路径（可选）</label>
                      <input
                        style={S.formInput}
                        value={translateOutput}
                        onChange={(e) => setTranslateOutput(e.target.value)}
                        placeholder="留空则自动生成 _zh 后缀文件"
                      />
                    </div>
                  </div>
                </div>
              </div>

              {/* Translation config */}
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.Arrow /> 翻译配置
                </div>
                <div style={S.panelBody}>
                  <div style={S.formGrid}>
                    <div style={S.formField}>
                      <label style={S.formLabel}>翻译服务</label>
                      <select
                        style={S.formInput}
                        value={translateProvider}
                        onChange={(e) => setTranslateProvider(e.target.value)}
                      >
                        <option value="deepseek">DeepSeek</option>
                        <option value="openai">OpenAI</option>
                      </select>
                    </div>
                    <div style={S.twoColForm}>
                      <div style={S.formField}>
                        <label style={S.formLabel}>源语言</label>
                        <select style={S.formInput} value={translateSrcLang} onChange={(e) => setTranslateSrcLang(e.target.value)}>
                          <option value="ja">日语 (ja)</option>
                          <option value="en">英语 (en)</option>
                          <option value="zh">中文 (zh)</option>
                        </select>
                      </div>
                      <div style={S.formField}>
                        <label style={S.formLabel}>目标语言</label>
                        <select style={S.formInput} value={translateTgtLang} onChange={(e) => setTranslateTgtLang(e.target.value)}>
                          <option value="zh">中文 (zh)</option>
                          <option value="en">英语 (en)</option>
                          <option value="ja">日语 (ja)</option>
                        </select>
                      </div>
                    </div>
                    <label style={S.checkboxField}>
                      <input
                        type="checkbox"
                        checked={translateBilingual}
                        onChange={(e) => setTranslateBilingual(e.target.checked)}
                      />
                      <span>生成双语字幕（原文 + 译文）</span>
                    </label>
                  </div>
                </div>
              </div>

              {/* Execute */}
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <button
                  style={{ ...S.btn, ...S.btnPrimary, padding: '10px 24px' }}
                  onClick={handleTranslate}
                  disabled={!translatePath || !!loading}
                >
                  <Icon.Arrow /> {loading === 'translate' ? '翻译中...' : '开始翻译'}
                </button>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  翻译将作为后台任务执行，可在任务中心查看进度
                </span>
              </div>

            </div>

            {/* Right: help */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.Info /> 说明
                </div>
                <div style={{ ...S.panelBody, ...S.helpText }}>
                  <p style={{ marginBottom: 12 }}>翻译功能调用 LLM 服务对字幕文件进行逐条翻译，支持输出双语格式。</p>
                  <p style={{ marginBottom: 12 }}><strong style={{ color: 'var(--fg)' }}>工作流程：</strong></p>
                  <ol style={{ paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <li>选择要翻译的字幕文件</li>
                    <li>配置翻译服务和语言方向</li>
                    <li>点击"开始翻译"提交后台任务</li>
                    <li>在任务中心查看翻译进度</li>
                    <li>完成后可在编辑器中打开结果</li>
                  </ol>
                  <p style={{ marginTop: 12 }}><strong style={{ color: 'var(--fg)' }}>注意事项：</strong></p>
                  <ul style={{ paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <li>翻译通过 LLM API 执行，需要配置有效的 API Key</li>
                    <li>大文件翻译可能需要较长时间</li>
                    <li>双语模式会在每条原文下方添加译文</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Workspace 3: Script to Subtitle ─────────────── */}
      <div style={S.workspace(activeTab === 'script')}>
        <div style={S.scrollWorkspace}>
          {/* Mode selector */}
          <div>
            <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600, marginBottom: 12 }}>
              台本转字幕
            </h2>
            <div style={S.modeSelector}>
              <div
                style={S.modeCard(scriptMode === 'text_only')}
                onClick={() => setScriptMode('text_only')}
              >
                <div style={S.modeCardIcon(scriptMode === 'text_only')}>
                  <Icon.Text />
                </div>
                <div style={S.modeCardTitle(scriptMode === 'text_only')}>纯文本模式</div>
                <div style={S.modeCardDesc}>仅从台本文件提取文本，LLM 清洗后生成字幕。适合无音频场景。</div>
              </div>
              <div
                style={S.modeCard(scriptMode === 'full')}
                onClick={() => setScriptMode('full')}
              >
                <div style={S.modeCardIcon(scriptMode === 'full')}>
                  <Icon.Audio />
                </div>
                <div style={S.modeCardTitle(scriptMode === 'full')}>音频对齐模式</div>
                <div style={S.modeCardDesc}>台本 + 音频文件，ASR 识别后与台本对齐，生成带精确时间轴的字幕。</div>
              </div>
              <div
                style={S.modeCard(scriptMode === 'existing_vtt')}
                onClick={() => setScriptMode('existing_vtt')}
              >
                <div style={S.modeCardIcon(scriptMode === 'existing_vtt')}>
                  <Icon.Vtt />
                </div>
                <div style={S.modeCardTitle(scriptMode === 'existing_vtt')}>VTT 重对齐模式</div>
                <div style={S.modeCardDesc}>基于已有的 VTT 文件，结合台本重新对齐和清洗。适合修正时间轴。</div>
              </div>
            </div>
          </div>

          <div style={S.twoColLayout}>
            {/* Left: params */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Script file */}
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.File /> 台本文件
                </div>
                <div style={S.panelBody}>
                  <div style={S.formGrid}>
                    <div style={S.formField}>
                      <label style={S.formLabel}>台本文件路径 *</label>
                      <div style={S.fileInput}>
                        <input
                          style={{ ...S.formInput, flex: 1 }}
                          value={scriptPath}
                          onChange={(e) => setScriptPath(e.target.value)}
                          placeholder="选择台本文件 (.pdf / .txt)"
                        />
                        <button
                          style={{ ...S.btn, ...S.btnSm }}
                          onClick={async () => {
                            const files = await selectFiles({
                              multiple: false,
                              filters: [FILE_FILTERS.script],
                              browserPrompt: '请输入台本文件所在目录的完整路径：',
                            })
                            if (files.length > 0) setScriptPath(files[0]!)
                          }}
                        >
                          浏览
                        </button>
                      </div>
                      <div style={S.formHint}>支持 PDF 和纯文本格式</div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Audio file (mode: full) */}
              {scriptMode === 'full' && (
                <div style={S.panel}>
                  <div style={S.panelHeader}>
                    <Icon.Audio /> 音频文件
                  </div>
                  <div style={S.panelBody}>
                    <div style={S.formGrid}>
                      <div style={S.formField}>
                        <label style={S.formLabel}>音频文件路径</label>
                        <div style={S.fileInput}>
                          <input
                            style={{ ...S.formInput, flex: 1 }}
                            value={audioPath}
                            onChange={(e) => setAudioPath(e.target.value)}
                            placeholder="选择音频文件 (.mp3 / .wav)"
                          />
                          <button
                            style={{ ...S.btn, ...S.btnSm }}
                            onClick={async () => {
                              const files = await selectFiles({
                                multiple: false,
                                filters: [FILE_FILTERS.audio],
                                browserPrompt: '请输入音频文件所在目录的完整路径：',
                              })
                              if (files.length > 0) {
                                setAudioPath(files[0]!)
                                audioPlayer.show(files[0]!, files[0]!.split(/[/\\]/).pop() || '台本音频')
                              }
                            }}
                          >
                            浏览
                          </button>
                        </div>
                      </div>
                      <div style={S.formField}>
                        <label style={S.formLabel}>音轨索引</label>
                        <select style={S.formInput} value={trackIndex} onChange={(e) => setTrackIndex(e.target.value)}>
                          <option value="">自动检测</option>
                          <option value="0">Track 0</option>
                          <option value="1">Track 1</option>
                          <option value="2">Track 2</option>
                          <option value="3">Track 3</option>
                        </select>
                        <div style={S.formHint}>多音轨文件选择要处理的音轨</div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* VTT file (mode: existing_vtt) */}
              {scriptMode === 'existing_vtt' && (
                <div style={S.panel}>
                  <div style={S.panelHeader}>
                    <Icon.Vtt /> 已有 VTT 文件
                  </div>
                  <div style={S.panelBody}>
                    <div style={S.formGrid}>
                      <div style={S.formField}>
                        <label style={S.formLabel}>VTT 文件路径</label>
                        <div style={S.fileInput}>
                          <input
                            style={{ ...S.formInput, flex: 1 }}
                            value={vttPath}
                            onChange={(e) => setVttPath(e.target.value)}
                            placeholder="选择 VTT 文件"
                          />
                          <button
                            style={{ ...S.btn, ...S.btnSm }}
                            onClick={async () => {
                              const files = await selectFiles({
                                multiple: false,
                                filters: [FILE_FILTERS.vtt],
                                browserPrompt: '请输入 VTT 文件所在目录的完整路径：',
                              })
                              if (files.length > 0) setVttPath(files[0]!)
                            }}
                          >
                            浏览
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Processing options */}
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 16 16">
                    <circle cx="8" cy="8" r="2.5" /><path d="M8 2.5v2M8 11.5v2M2.5 8h2M11.5 8h2" />
                  </svg>
                  处理参数
                </div>
                <div style={S.panelBody}>
                  <div style={S.formGrid}>
                    <div style={S.twoColForm}>
                      <div style={S.formField}>
                        <label style={S.formLabel}>输出格式</label>
                        <select style={S.formInput} value={scriptFmt} onChange={(e) => setScriptFmt(e.target.value)}>
                          <option value="vtt">WebVTT (.vtt)</option>
                          <option value="srt">SRT (.srt)</option>
                          <option value="lrc">LRC (.lrc)</option>
                        </select>
                      </div>
                      {scriptMode === 'full' && (
                        <div style={S.formField}>
                          <label style={S.formLabel}>ASR 模型</label>
                          <select style={S.formInput} value={asrModelSize} onChange={(e) => setAsrModelSize(e.target.value)}>
                            <option value="large-v3">large-v3 (推荐)</option>
                            <option value="base">base (快速)</option>
                            <option value="small">small</option>
                            <option value="medium">medium</option>
                          </select>
                        </div>
                      )}
                    </div>
                    <div style={S.twoColForm}>
                      {scriptMode === 'full' && (
                        <div style={S.formField}>
                          <label style={S.formLabel}>音频语言</label>
                          <select style={S.formInput} value={asrLanguage} onChange={(e) => setAsrLanguage(e.target.value)}>
                            <option value="ja">日语 (ja)</option>
                            <option value="en">英语 (en)</option>
                            <option value="zh">中文 (zh)</option>
                          </select>
                        </div>
                      )}
                      <div style={S.formField}>
                        <label style={S.formLabel}>竖排模式</label>
                        <select style={S.formInput} value={verticalMode} onChange={(e) => setVerticalMode(e.target.value)}>
                          <option value="auto">自动检测</option>
                          <option value="horizontal">横排</option>
                          <option value="vertical">竖排</option>
                        </select>
                      </div>
                    </div>
                    <label style={S.checkboxField}>
                      <input
                        type="checkbox"
                        checked={useLlmClean}
                        onChange={(e) => setUseLlmClean(e.target.checked)}
                      />
                      <span>启用 LLM 文本清洗</span>
                    </label>
                  </div>
                </div>
              </div>

              {/* Execute */}
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <button
                  style={{ ...S.btn, ...S.btnPrimary, padding: '10px 24px' }}
                  onClick={handleScriptToVtt}
                  disabled={!scriptPath || !!loading}
                >
                  <Icon.Start /> {loading === 'script' ? '转换中...' : '开始转换'}
                </button>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  转换将在后台执行，可在任务中心查看进度
                </span>
              </div>
            </div>

            {/* Right: result + help */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.Check /> 转换结果
                </div>
                <div style={{ ...S.panelBody, color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: 24 }}>
                  提交后将在任务中心显示阶段、错误和输出文件
                </div>
              </div>

              {/* Mode help */}
              <div style={S.panel}>
                <div style={S.panelHeader}>
                  <Icon.Info /> 模式说明
                </div>
                <div style={{ ...S.panelBody, ...S.helpText }}>
                  <p style={{ marginBottom: 8 }}>
                    <strong style={{ color: 'var(--fg)' }}>纯文本模式</strong> — 从台本提取文本，LLM 清洗后直接生成字幕。不含精确时间轴。
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong style={{ color: 'var(--fg)' }}>音频对齐模式</strong> — ASR 识别音频 → 与台本对齐 → 生成带时间轴的字幕。精度最高。
                  </p>
                  <p>
                    <strong style={{ color: 'var(--fg)' }}>VTT 重对齐模式</strong> — 已有 VTT 文件 + 台本，重新清洗和对齐。适合修正错误。
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
