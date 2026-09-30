import { useCallback } from 'react'
import { create } from 'zustand'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, ReferenceCandidate, ReferenceDraft, ReferenceInspection } from '@/api/speech'
import type { TaskStatusResponse } from '@/api/types'
import { ApiError } from '@/api/client'
import { chronologicalSegments } from '@/pages/voice-lab/referenceAnalysis'
import { sameClip } from '@/pages/voice-lab/referencePlayback'

export type ReferenceEditorDraft = Omit<ReferenceDraft, 'path'>
export const initialReferenceDraft = (): ReferenceEditorDraft => ({ name: '', notes: '', start: 0, end: 0, transcript: '', language: 'auto', confirmed: false, gain_db: 0, fade_in: 0, fade_out: 0 })
type ClipSnapshot = { path: string; start: number; end: number; language: string; transcript: string }
interface ReferenceSession {
  source: ReferenceInspection | null
  stored: ReferenceAsset | null
  draft: ReferenceEditorDraft
  view: 'editor' | 'saved'
  dirty: boolean
  busy: string
  error: string
  notice: string
  candidates: ReferenceCandidate[]
  analyzed: boolean
  analysisError: string
  analysisTask: TaskStatusResponse | null
  recognizeText: boolean
  analysisWarnings: string[]
  analysisSource: string
  trackingFailed: boolean
  trackingRetry: number
  loadedSubtitle: { name: string; subtitle_text: string; subtitle_format: 'vtt' | 'srt' } | null
  preview: ReferenceInspection | null
  segments: { start: number; end: number; text: string }[]
  loop: boolean
  assistOpen: boolean
  subtitleRole: 'reference' | 'original'
  showArchived: boolean
  query: string
  clipTask: TaskStatusResponse | null
  clipSubmitting: boolean
  clipError: string
  clipNote: string
  clipRetry: number
  clipDisconnected: boolean
  clipRequest: ClipSnapshot | null
  clipResult: { text: string; snapshot: ClipSnapshot } | null
}

export const useReferenceSessionStore = create<ReferenceSession>(() => ({
  source: null, stored: null, draft: initialReferenceDraft(), view: 'editor', dirty: false,
  busy: '', error: '', notice: '', candidates: [], analyzed: false, analysisError: '', analysisTask: null,
  recognizeText: true, analysisWarnings: [], analysisSource: '', trackingFailed: false, trackingRetry: 0,
  loadedSubtitle: null, preview: null, segments: [], loop: false, assistOpen: false, subtitleRole: 'reference',
  showArchived: false, query: '', clipTask: null, clipSubmitting: false, clipError: '', clipNote: '',
  clipRetry: 0, clipDisconnected: false, clipRequest: null, clipResult: null,
}))

// The session survives React unmounts. It is intentionally not persisted across app restarts.
export function useReferenceField<K extends keyof ReferenceSession>(key: K) {
  const value = useReferenceSessionStore(state => state[key])
  const setValue = useCallback((next: ReferenceSession[K] | ((previous: ReferenceSession[K]) => ReferenceSession[K])) => {
    useReferenceSessionStore.setState(state => ({ [key]: typeof next === 'function' ? (next as (previous: ReferenceSession[K]) => ReferenceSession[K])(state[key]) : next }) as Pick<ReferenceSession, K>)
  }, [key])
  return [value, setValue] as const
}

const store = useReferenceSessionStore
const terminal = (task: TaskStatusResponse) => ['completed', 'failed', 'cancelled', 'skipped'].includes(task.state)
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

export async function startReferenceAnalysis() {
  const session = store.getState()
  if (!session.source || session.busy || (session.analysisTask && !terminal(session.analysisTask))) return
  const source = session.source
  store.setState({ busy: '正在提交片段分析', assistOpen: true, analysisError: '', candidates: [], analyzed: false, analysisWarnings: [], analysisSource: '' })
  try {
    const task = await speechApi.analyzeTask(source.path, session.draft.language, session.recognizeText, session.loadedSubtitle || undefined)
    if (store.getState().source === source) store.setState({ analysisTask: task })
  } catch (cause) {
    if (store.getState().source === source) store.setState({ analysisError: message(cause), analyzed: true })
  } finally {
    if (store.getState().source === source) store.setState({ busy: '' })
  }
}

export async function startReferenceTranscription() {
  const state = store.getState()
  if (!state.source || state.clipSubmitting || (state.clipTask && !terminal(state.clipTask))) return
  const source = state.source
  const snapshot = { path: source.path, start: state.draft.start, end: state.draft.end, language: state.draft.language, transcript: state.draft.transcript }
  if (!Number.isFinite(snapshot.start) || !Number.isFinite(snapshot.end) || snapshot.start < 0 || snapshot.end <= snapshot.start || snapshot.end > source.duration) return
  store.setState({ clipSubmitting: true, clipRequest: snapshot, clipError: '', clipNote: '', clipResult: null })
  try {
    const task = await speechApi.transcribeTask(snapshot.path, snapshot.start, snapshot.end, snapshot.language)
    if (store.getState().source === source) store.setState({ clipTask: task })
  } catch (cause) {
    if (store.getState().source === source) store.setState({ clipError: message(cause) })
  } finally {
    if (store.getState().source === source) store.setState({ clipSubmitting: false })
  }
}

// One observer per task kind, independent of page mounting. Source identity + generation
// discard late replies, including reopening the same file as a new draft.
function trackTask(kind: 'analysis' | 'clip') {
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const taskKey = kind === 'analysis' ? 'analysisTask' : 'clipTask'
  const retryKey = kind === 'analysis' ? 'trackingRetry' : 'clipRetry'
  const errorKey = kind === 'analysis' ? 'analysisError' : 'clipError'
  const disconnectedKey = kind === 'analysis' ? 'trackingFailed' : 'clipDisconnected'
  const start = () => {
    const ticket = ++generation
    clearTimeout(timer)
    const source = store.getState().source
    const task = store.getState()[taskKey]
    if (!source || !task) return
    let failures = 0
    store.setState({ [disconnectedKey]: false })
    const current = () => ticket === generation && store.getState().source === source && store.getState()[taskKey]?.task_id === task.task_id
    async function poll() {
      try {
        const response = kind === 'analysis' ? await speechApi.analysisStatus(task!.task_id) : await speechApi.transcriptionStatus(task!.task_id)
        if (!current()) return
        failures = 0
        const status = response.status
        store.setState({ [taskKey]: status, [errorKey]: '' })
        if (status.state === 'completed') {
          if (kind === 'analysis') {
            const result = response.result as Awaited<ReturnType<typeof speechApi.analysisStatus>>['result']
            if (!result) { store.setState({ analysisError: '分析任务已结束，但未返回片段结果。请重新分析。', analyzed: true }); return }
            store.setState({ candidates: chronologicalSegments(result.segments), analyzed: true, analysisWarnings: result.warnings || [], analysisSource: result.transcript_source === 'subtitle' ? `已复用字幕：${result.subtitle?.name || '同目录字幕'}，未运行 ASR。` : result.transcript_source === 'asr' ? '原文来自本次 ASR，仍需试听核对。' : '未运行 ASR，请在上方手动试听选段。' })
          } else {
            const result = response.result as Awaited<ReturnType<typeof speechApi.transcriptionStatus>>['result']
            const text = result?.transcript?.trim()
            const state = store.getState(), snapshot = state.clipRequest
            if (!text || !snapshot) { store.setState({ clipError: '未识别到原文，请试听检查选段后重试。' }); return }
            if (sameClip(snapshot, { path: source!.path, ...state.draft }) && snapshot.transcript === state.draft.transcript) {
              store.setState({ draft: { ...state.draft, transcript: text, confirmed: false }, dirty: true, preview: null, clipNote: '已填入选段原文，请试听核对。' })
            } else store.setState({ clipResult: { text, snapshot }, clipNote: '识别期间选段、语言或原文已修改，结果未自动覆盖。' })
          }
          return
        }
        if (terminal(status)) {
          store.setState({ [errorKey]: String(status.error?.message || status.detail || status.message || '识别已取消或未完成。'), ...(kind === 'analysis' ? { analyzed: true } : {}) })
          return
        }
      } catch (cause) {
        if (!current()) return
        store.setState({ [errorKey]: message(cause) })
        if (cause instanceof ApiError && cause.status === 404) {
          store.setState({ [errorKey]: '任务已不存在，后端可能已重启。请重新识别。', [taskKey]: null, ...(kind === 'analysis' ? { analyzed: true } : {}) })
          return
        }
        if (++failures >= 3) { store.setState({ [disconnectedKey]: true }); return }
      }
      if (current()) timer = setTimeout(() => void poll(), 1500)
    }
    void poll()
  }
  const unsubscribe = store.subscribe((next, previous) => {
    if (next.source !== previous.source || next[taskKey]?.task_id !== previous[taskKey]?.task_id || next[retryKey] !== previous[retryKey]) start()
  })
  return () => { unsubscribe(); generation++; clearTimeout(timer) }
}

store.subscribe((next, previous) => {
  if (next.source !== previous.source) store.setState({ clipTask: null, clipSubmitting: false, clipRequest: null, clipResult: null, clipError: '', clipNote: '', clipDisconnected: false })
})
const stopAnalysis = trackTask('analysis')
const stopClip = trackTask('clip')
const beforeUnload = (event: BeforeUnloadEvent) => {
  if (store.getState().dirty) { event.preventDefault(); event.returnValue = '' }
}
window.addEventListener('beforeunload', beforeUnload)
if (import.meta.hot) import.meta.hot.dispose(() => { stopAnalysis(); stopClip(); window.removeEventListener('beforeunload', beforeUnload) })
