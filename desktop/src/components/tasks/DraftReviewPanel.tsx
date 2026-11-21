import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiUrl, ApiError } from '@/api/client'
import { draftsApi } from '@/api/drafts'
import type {
  DraftCommitRequest,
  DraftDetail,
  DraftPatchRequest,
  DraftReferenceCandidate,
  DraftSampleTake,
  DraftSegment,
  DraftSegmentEdit,
  DraftState,
  OverSpeedCueItem,
  QualityAuditReport,
} from '@/api/types'
import { t, format as formatMessage, useI18n } from '@/i18n'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { confirmAction } from '@/utils/confirmAction'
import { displayPath } from '@/utils/displayPath'
import './DraftReviewPanel.css'

export type SegmentFilterMode = 'all' | 'warnings'

export interface SegmentWarningInfo {
  index: number
  untranslated: boolean
  japaneseResidue: boolean
  blockingEmpty: boolean
  overSpeed: OverSpeedCueItem | null
  hasWarning: boolean
}

export interface CommitFormOptions {
  outputDir: string
  exportSrt: boolean
  exportLrc: boolean
  bilingual?: boolean
  enableDubbing: boolean
  regenerateCueIds?: string[]
  mixOptions?: Record<string, unknown> | null
  expectedRevision?: number | null
}

export interface AudioPlayerActions {
  show: (src: string, title: string) => void
  seek: (time: number) => void
  setPlaying: (playing: boolean) => void
}

export interface DraftReviewPanelProps {
  initialDrafts?: DraftDetail[]
  initialSelectedDraftId?: string | null
  initialFilter?: SegmentFilterMode
  initialEdits?: Record<number, string>
}

const SPEECH_CHAR_RE = /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7afA-Za-z0-9]/
const ACTIVE_DRAFT_STATES = new Set<DraftState>(['preparing', 'committing'])

export const DRAFT_STATE_LABELS: Record<string, string> = {
  awaiting_review: '待确认',
  preparing: '准备草稿中',
  committing: '正在合成交付',
  completed: '已完成交付',
  failed: '失败',
}

export function hasSpeakableText(text: string): boolean {
  return SPEECH_CHAR_RE.test((text || '').trim())
}

export function normalizeAuditReport(raw?: Partial<QualityAuditReport> | null): QualityAuditReport {
  const summary = raw?.summary_counts ?? {}
  return {
    draft_id: raw?.draft_id ?? null,
    state: raw?.state ?? null,
    revision: raw?.revision ?? null,
    untranslated_indices: Array.isArray(raw?.untranslated_indices) ? [...raw.untranslated_indices] : [],
    japanese_residue_indices: Array.isArray(raw?.japanese_residue_indices) ? [...raw.japanese_residue_indices] : [],
    empty_or_symbol_indices: Array.isArray(raw?.empty_or_symbol_indices) ? [...raw.empty_or_symbol_indices] : [],
    over_speed_cues: Array.isArray(raw?.over_speed_cues) ? [...raw.over_speed_cues] : [],
    summary_counts: { ...summary },
    gate_passed: Boolean(raw?.gate_passed),
    script_alignment: raw?.script_alignment,
    chars_per_second: typeof raw?.chars_per_second === 'number' && Number.isFinite(raw.chars_per_second)
      ? raw.chars_per_second
      : 4.2,
    max_atempo: typeof raw?.max_atempo === 'number' && Number.isFinite(raw.max_atempo)
      ? raw.max_atempo
      : 1.35,
    reference_quality: raw?.reference_quality ?? null,
    warnings: Array.isArray(raw?.warnings) ? [...raw.warnings] : [],
  }
}

export function collectSegmentWarnings(
  segments: DraftSegment[],
  audit: QualityAuditReport,
): Map<number, SegmentWarningInfo> {
  const untranslatedSet = new Set(audit.untranslated_indices)
  const residueSet = new Set(audit.japanese_residue_indices)
  const emptySet = new Set(audit.empty_or_symbol_indices)
  const overSpeedMap = new Map<number, OverSpeedCueItem>()
  for (const item of audit.over_speed_cues) {
    overSpeedMap.set(item.index, item)
  }

  const map = new Map<number, SegmentWarningInfo>()
  segments.forEach((seg, idx) => {
    const segIndex = typeof seg.index === 'number' ? seg.index : idx
    const untranslated = untranslatedSet.has(segIndex)
    const japaneseResidue = residueSet.has(segIndex)
    const blockingEmpty = emptySet.has(segIndex) && hasSpeakableText(seg.source_text)
    const overSpeed = overSpeedMap.get(segIndex) ?? null
    map.set(segIndex, {
      index: segIndex,
      untranslated,
      japaneseResidue,
      blockingEmpty,
      overSpeed,
      hasWarning: untranslated || japaneseResidue || blockingEmpty || overSpeed !== null,
    })
  })
  return map
}

export function filterReviewSegments(
  segments: DraftSegment[],
  warnings: Map<number, SegmentWarningInfo>,
  mode: SegmentFilterMode,
): DraftSegment[] {
  if (mode === 'all') return segments
  return segments.filter((seg, idx) => {
    const segIndex = typeof seg.index === 'number' ? seg.index : idx
    return Boolean(warnings.get(segIndex)?.hasWarning)
  })
}

export function buildDraftPatchRequest(
  segments: DraftSegment[],
  editedTranslations: Record<number, string>,
  expectedRevision: number,
  editedDeliveries?: Record<number, string>,
): DraftPatchRequest {
  const edits: DraftSegmentEdit[] = []
  segments.forEach((seg, idx) => {
    const segIndex = typeof seg.index === 'number' ? seg.index : idx
    const draftValue = editedTranslations[segIndex]
    const deliveryValue = editedDeliveries?.[segIndex]
    const translationChanged = draftValue !== undefined && draftValue !== (seg.translation ?? '')
    const deliveryChanged = deliveryValue !== undefined && deliveryValue !== (seg.delivery ?? 'normal')
    if (!translationChanged && !deliveryChanged) return
    edits.push({
      index: segIndex,
      cue_id: seg.cue_id,
      ...(translationChanged ? { translation: draftValue } : {}),
      ...(deliveryChanged ? { delivery: deliveryValue } : {}),
    })
  })
  return {
    edits,
    expected_revision: expectedRevision,
  }
}

export function applyPatchedDraftState(
  drafts: DraftDetail[],
  updated: DraftDetail,
  refreshedAudit?: QualityAuditReport | null,
): DraftDetail[] {
  const merged: DraftDetail = refreshedAudit
    ? { ...updated, audit_report: refreshedAudit }
    : updated
  const exists = drafts.some((item) => item.draft_id === merged.draft_id)
  const next = exists
    ? drafts.map((item) => (item.draft_id === merged.draft_id ? merged : item))
    : [merged, ...drafts]
  return sortDraftSessions(next)
}

export function defaultCommitOutputDir(workDir: string): string {
  const trimmed = (workDir || '').trim().replace(/[\\/]+$/, '')
  return trimmed ? `${trimmed}/output` : 'output'
}

export function buildDraftCommitRequest(options: CommitFormOptions): DraftCommitRequest {
  const exportFormats: string[] = []
  if (options.exportSrt) exportFormats.push('srt')
  if (options.exportLrc) exportFormats.push('lrc')
  return {
    output_dir: options.outputDir.trim(),
    export_formats: exportFormats,
    enable_dubbing: options.enableDubbing,
    bilingual: options.bilingual ?? true,
    ...(options.regenerateCueIds && options.regenerateCueIds.length > 0
      ? { regenerate_cue_ids: options.regenerateCueIds }
      : {}),
    ...(options.mixOptions ? { mix_options: options.mixOptions } : {}),
    expected_revision: options.expectedRevision ?? null,
  }
}

export function getReferenceCandidate(
  draft: DraftDetail,
  audit: QualityAuditReport,
): DraftReferenceCandidate | null {
  if (audit.reference_quality?.path) return audit.reference_quality
  if (draft.artifacts?.reference_candidate?.path) return draft.artifacts.reference_candidate
  const planRef = draft.voice_plan?.reference_candidate as DraftReferenceCandidate | undefined
  if (planRef?.path) return planRef
  return null
}

export function getSampleTakes(draft: DraftDetail): DraftSampleTake[] {
  if (Array.isArray(draft.artifacts?.sample_takes) && draft.artifacts.sample_takes.length > 0) {
    return draft.artifacts.sample_takes
  }
  const planTakes = draft.voice_plan?.sample_takes
  if (Array.isArray(planTakes)) {
    return planTakes as DraftSampleTake[]
  }
  return []
}

export function resolveSampleTakeAudioSrc(take: DraftSampleTake): string {
  if (take.take_id && take.take_id.trim()) {
    return apiUrl(`/speech/takes/${encodeURIComponent(take.take_id.trim())}/audio`)
  }
  return take.audio_path || ''
}

export function playClipInAudioBar(
  player: AudioPlayerActions,
  src: string,
  title: string,
  startSec?: number,
): boolean {
  const trimmed = (src || '').trim()
  if (!trimmed) return false
  player.show(trimmed, title)
  if (typeof startSec === 'number' && Number.isFinite(startSec) && startSec >= 0) {
    player.seek(startSec)
  }
  player.setPlaying(true)
  return true
}

export function sortDraftSessions(drafts: DraftDetail[]): DraftDetail[] {
  return drafts.slice().sort((left, right) => (
    right.updated_at.localeCompare(left.updated_at) ||
    right.created_at.localeCompare(left.created_at) ||
    right.draft_id.localeCompare(left.draft_id)
  ))
}

export function formatCueSeconds(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '00:00.00'
  const minutes = Math.floor(sec / 60)
  const remainder = sec - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${remainder.toFixed(2).padStart(5, '0')}`
}

export function formatCueTimeRange(start: number, end: number): string {
  return `${formatCueSeconds(start)} - ${formatCueSeconds(end)}`
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const ts = Date.parse(value)
  return Number.isNaN(ts) ? value : new Date(ts).toLocaleString()
}

export default function DraftReviewPanel({
  initialDrafts,
  initialSelectedDraftId,
  initialFilter = 'all',
  initialEdits,
}: DraftReviewPanelProps = {}) {
  useI18n()
  const showAudio = useAudioPlayerStore((state) => state.show)
  const seekAudio = useAudioPlayerStore((state) => state.seek)
  const setAudioPlaying = useAudioPlayerStore((state) => state.setPlaying)

  const [drafts, setDrafts] = useState<DraftDetail[]>(() => (
    initialDrafts ? sortDraftSessions(initialDrafts) : []
  ))
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(() => {
    if (initialSelectedDraftId !== undefined) return initialSelectedDraftId
    if (!initialDrafts?.length) return null
    const ordered = sortDraftSessions(initialDrafts)
    return ordered.find((d) => d.state === 'awaiting_review')?.draft_id ?? ordered[0]?.draft_id ?? null
  })
  const [loadingList, setLoadingList] = useState(() => !initialDrafts)
  const [listError, setListError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [savingPatch, setSavingPatch] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [filterMode, setFilterMode] = useState<SegmentFilterMode>(initialFilter)
  const [editedTranslations, setEditedTranslations] = useState<Record<number, string>>(
    () => (initialEdits ? { ...initialEdits } : {}),
  )
  const [editedDeliveries, setEditedDeliveries] = useState<Record<number, string>>({})
  const [retakeCueIds, setRetakeCueIds] = useState<string[]>([])
  const [sidechainDucking, setSidechainDucking] = useState(true)
  const [roomToneInpaint, setRoomToneInpaint] = useState(false)
  const [binauralMode, setBinauralMode] = useState<'dynamic_hrtf' | 'static' | 'off'>('dynamic_hrtf')

  const selectedDraft = useMemo(
    () => drafts.find((item) => item.draft_id === selectedDraftId) ?? null,
    [drafts, selectedDraftId],
  )

  const [outputDir, setOutputDir] = useState<string>(() => (
    selectedDraft ? (selectedDraft.artifacts?.output_dir || defaultCommitOutputDir(selectedDraft.work_dir)) : ''
  ))
  const [exportSrt, setExportSrt] = useState(true)
  const [exportLrc, setExportLrc] = useState(true)
  const [bilingual, setBilingual] = useState(true)
  const [enableDubbing, setEnableDubbing] = useState(true)

  const listReqRef = useRef(0)
  const prevSelectedIdRef = useRef<string | null>(selectedDraft?.draft_id ?? null)

  useEffect(() => {
    const currentId = selectedDraft?.draft_id ?? null
    if (currentId === prevSelectedIdRef.current) return
    prevSelectedIdRef.current = currentId
    setEditedTranslations({})
    setEditedDeliveries({})
    setRetakeCueIds([])
    setActionError('')
    setNotice('')
    if (selectedDraft) {
      setOutputDir(selectedDraft.artifacts?.output_dir || defaultCommitOutputDir(selectedDraft.work_dir))
      setEnableDubbing(selectedDraft.tracks.length > 0)
    } else {
      setOutputDir('')
    }
  }, [selectedDraft])

  const loadDraftList = useCallback(async () => {
    const reqId = listReqRef.current + 1
    listReqRef.current = reqId
    setLoadingList(true)
    setListError('')
    try {
      const response = await draftsApi.list()
      if (listReqRef.current !== reqId) return
      const ordered = sortDraftSessions(response.drafts)
      setDrafts(ordered)
      setSelectedDraftId((current) => {
        if (current && ordered.some((item) => item.draft_id === current)) return current
        return ordered.find((item) => item.state === 'awaiting_review')?.draft_id ?? ordered[0]?.draft_id ?? null
      })
    } catch (error) {
      if (listReqRef.current === reqId) {
        setListError(formatMessage('读取草稿列表失败：{0}', [String(error)]))
      }
    } finally {
      if (listReqRef.current === reqId) setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    if (initialDrafts) return
    void loadDraftList()
    return () => {
      listReqRef.current += 1
    }
  }, [initialDrafts, loadDraftList])

  const reloadSelectedDraft = useCallback(async (draftId: string) => {
    try {
      const fresh = await draftsApi.get(draftId)
      const freshAudit = typeof draftsApi.getAudit === 'function'
        ? await draftsApi.getAudit(draftId).catch(() => null)
        : null
      setDrafts((current) => current.some(item => item.draft_id === draftId)
        ? applyPatchedDraftState(current, fresh, freshAudit) : current)
      setActionError('')
    } catch (error) {
      setActionError(formatMessage('读取草稿详情失败：{0}', [String(error)]))
    }
  }, [])

  // Poll active preparing/committing drafts until settled
  useEffect(() => {
    if (!selectedDraft || !ACTIVE_DRAFT_STATES.has(selectedDraft.state) || savingPatch || committing) return
    let disposed = false
    const draftId = selectedDraft.draft_id
    const timer = window.setTimeout(() => {
      if (!disposed) void reloadSelectedDraft(draftId)
    }, 2000)
    return () => {
      disposed = true
      window.clearTimeout(timer)
    }
  }, [committing, reloadSelectedDraft, savingPatch, selectedDraft])

  const audit = useMemo(
    () => normalizeAuditReport(selectedDraft?.audit_report),
    [selectedDraft?.audit_report],
  )

  const segmentWarnings = useMemo(
    () => collectSegmentWarnings(selectedDraft?.segments ?? [], audit),
    [audit, selectedDraft?.segments],
  )

  const warningCueCount = useMemo(() => {
    let count = 0
    for (const info of segmentWarnings.values()) {
      if (info.hasWarning) count += 1
    }
    return count
  }, [segmentWarnings])

  const visibleSegments = useMemo(
    () => filterReviewSegments(selectedDraft?.segments ?? [], segmentWarnings, filterMode),
    [filterMode, segmentWarnings, selectedDraft?.segments],
  )

  const pendingPatch = useMemo(
    () => (
      selectedDraft
        ? buildDraftPatchRequest(selectedDraft.segments, editedTranslations, selectedDraft.revision, editedDeliveries)
        : { edits: [], expected_revision: null }
    ),
    [editedDeliveries, editedTranslations, selectedDraft],
  )

  const referenceCandidate = useMemo(
    () => (selectedDraft ? getReferenceCandidate(selectedDraft, audit) : null),
    [audit, selectedDraft],
  )

  const sampleTakes = useMemo(
    () => (selectedDraft ? getSampleTakes(selectedDraft) : []),
    [selectedDraft],
  )

  const primaryTrackPath = selectedDraft?.tracks[0]?.path || selectedDraft?.artifacts?.primary_track_path || ''
  const mixedAudioPath = selectedDraft?.artifacts?.mixed_audio_path || selectedDraft?.artifacts?.dubbing?.mixed_audio_path || ''

  const playerActions = useMemo<AudioPlayerActions>(
    () => ({ show: showAudio, seek: seekAudio, setPlaying: setAudioPlaying }),
    [seekAudio, setAudioPlaying, showAudio],
  )

  const handleSaveEdits = async () => {
    if (!selectedDraft || pendingPatch.edits.length === 0 || savingPatch || committing || deleting) return
    setSavingPatch(true)
    setActionError('')
    setNotice('')
    try {
      const updated = await draftsApi.patch(selectedDraft.draft_id, pendingPatch)
      const refreshedAudit = typeof draftsApi.getAudit === 'function'
        ? await draftsApi.getAudit(selectedDraft.draft_id).catch(() => null)
        : null
      setDrafts((current) => applyPatchedDraftState(current, updated, refreshedAudit))
      setEditedTranslations({})
      setEditedDeliveries({})
      setNotice(formatMessage('已保存 {0} 处台词修订（版本 r{1}）', [pendingPatch.edits.length, updated.revision]))
    } catch (error) {
      if (error instanceof ApiError && (error.code === 'REVISION_CONFLICT' || error.status === 409)) {
        setActionError(t('草稿版本冲突，请先刷新最新草稿后再保存修订。'))
      } else {
        setActionError(formatMessage('保存修订失败：{0}', [String(error)]))
      }
    } finally {
      setSavingPatch(false)
    }
  }

  const handleCommitDraft = async () => {
    if (!selectedDraft || savingPatch || committing || deleting) return
    const trimmedOut = outputDir.trim()
    if (!trimmedOut) {
      setActionError(t('请填写交付输出目录。'))
      return
    }
    if (!exportSrt && !exportLrc && !enableDubbing) {
      setActionError(t('请至少勾选一项导出字幕或配音混音交付项。'))
      return
    }

    setCommitting(true)
    setActionError('')
    setNotice('')
    try {
      let currentRevision = selectedDraft.revision
      if (pendingPatch.edits.length > 0) {
        const patched = await draftsApi.patch(selectedDraft.draft_id, pendingPatch)
        currentRevision = patched.revision
        setDrafts((current) => applyPatchedDraftState(current, patched))
        setEditedTranslations({})
        setEditedDeliveries({})
      }
      const commitPayload = buildDraftCommitRequest({
        outputDir: trimmedOut,
        exportSrt,
        exportLrc,
        bilingual,
        enableDubbing,
        regenerateCueIds: retakeCueIds,
        mixOptions: enableDubbing
          ? {
              sidechain_ducking: sidechainDucking,
              room_tone_inpaint: roomToneInpaint,
              binaural_mode: binauralMode,
            }
          : null,
        expectedRevision: currentRevision,
      })
      const committed = await draftsApi.commit(selectedDraft.draft_id, commitPayload)
      setDrafts((current) => applyPatchedDraftState(current, committed))
      setRetakeCueIds([])
      setOutputDir(committed.artifacts?.output_dir || trimmedOut)
      setNotice(
        retakeCueIds.length > 0
          ? formatMessage('已重抽 {0} 句并重新混音交付至：{1}', [retakeCueIds.length, displayPath(committed.artifacts?.output_dir || trimmedOut)])
          : formatMessage('已完成合成并交付至：{0}', [displayPath(committed.artifacts?.output_dir || trimmedOut)]),
      )
    } catch (error) {
      if (error instanceof ApiError && (error.code === 'REVISION_CONFLICT' || error.status === 409)) {
        setActionError(t('草稿版本冲突，请先刷新最新草稿后再确认合成。'))
      } else {
        setActionError(formatMessage('合成交付失败：{0}', [String(error)]))
      }
    } finally {
      setCommitting(false)
    }
  }

  const translatedCount = audit.summary_counts.translated_cues ?? (
    selectedDraft ? selectedDraft.segments.filter((seg) => hasSpeakableText(seg.translation)).length : 0
  )
  const totalCueCount = selectedDraft?.segments.length ?? 0
  const isBusyState = Boolean(selectedDraft && ACTIVE_DRAFT_STATES.has(selectedDraft.state))

  const handleDeleteDraft = async () => {
    if (!selectedDraft || isBusyState || deleting || savingPatch || committing) return
    const draft = selectedDraft
    setDeleting(true)
    setActionError('')
    try {
      if (!(await confirmAction(formatMessage('删除草稿「{0}」？', [draft.title || draft.draft_id])))) return
      await draftsApi.remove(draft.draft_id, draft.revision)
      setDrafts(current => current.filter(item => item.draft_id !== draft.draft_id))
      await loadDraftList()
    } catch (error) {
      setActionError(formatMessage('删除草稿失败：{0}', [String(error)]))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="draft-review-panel">
      <section className="draft-review-sidebar" aria-label={t('草稿列表')}>
        <div className="draft-sidebar-header">
          <div className="draft-sidebar-title">
            <strong>{t('草稿列表')}</strong>
            <span>{formatMessage('{0} 份草稿', [drafts.length])}</span>
          </div>
          <button
            type="button"
            className="draft-btn draft-btn--sm"
            disabled={loadingList || savingPatch || committing || deleting}
            onClick={() => { void loadDraftList() }}
          >
            {t('刷新草稿')}
          </button>
        </div>

        {listError ? (
          <div className="draft-notice draft-notice--error" style={{ margin: '10px 12px 0' }} role="alert">
            <div>{listError}</div>
          </div>
        ) : null}

        <div className="draft-list-scroll">
          {loadingList && drafts.length === 0 ? (
            <div className="draft-empty-state">{t('正在读取草稿会话…')}</div>
          ) : drafts.length === 0 ? (
            <div className="draft-empty-state">{t('暂无待审或历史草稿会话。')}</div>
          ) : drafts.map((draft) => {
            const isSelected = draft.draft_id === selectedDraftId
            const itemAudit = normalizeAuditReport(draft.audit_report)
            return (
              <button
                key={draft.draft_id}
                type="button"
                className={`draft-session-card ${isSelected ? 'is-selected' : ''}`}
                aria-pressed={isSelected}
                disabled={deleting}
                onClick={() => {
                  setSelectedDraftId(draft.draft_id)
                }}
              >
                <div className="draft-session-card__top">
                  <span className="draft-session-card__title">{draft.title || draft.draft_id}</span>
                  <span className={`draft-state-badge state-${draft.state}`}>
                    {t(DRAFT_STATE_LABELS[draft.state] || draft.state)}
                  </span>
                </div>
                <div className="draft-session-card__meta">
                  <span>{formatMessage('{0} 条音轨 · {1} 句台词', [draft.tracks.length, draft.segments.length])}</span>
                  <span>
                    {draft.segments.length > 0
                      ? (itemAudit.gate_passed ? t('检查通过') : t('需复核'))
                      : `r${draft.revision}`}
                  </span>
                </div>
                <div className="draft-session-card__meta" style={{ marginTop: 4 }}>
                  <span>{formatDateTime(draft.updated_at)}</span>
                  <span>r{draft.revision}</span>
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="draft-review-detail" aria-label={t('草稿复核详情')}>
        {!selectedDraft ? (
          <div className="draft-empty-state">{t('请在左侧选择一份草稿会话以查看质检报告与修订台词。')}</div>
        ) : (
          <>
            <header className="draft-detail-header">
              <div className="draft-detail-heading">
                <h2>{selectedDraft.title || selectedDraft.draft_id}</h2>
                <div className="draft-detail-submeta">
                  <span><code>{selectedDraft.draft_id}</code></span>
                  <span>{formatMessage('版本 r{0}', [selectedDraft.revision])}</span>
                  <span>{displayPath(selectedDraft.work_dir)}</span>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className={`draft-state-badge state-${selectedDraft.state}`}>
                  {t(DRAFT_STATE_LABELS[selectedDraft.state] || selectedDraft.state)}
                </span>
                <button
                  type="button"
                  className="draft-btn draft-btn--sm"
                  disabled={savingPatch || committing || deleting}
                  onClick={() => { void reloadSelectedDraft(selectedDraft.draft_id) }}
                >
                  {t('重新读取详情')}
                </button>
                {!isBusyState && <button type="button" className="draft-btn draft-btn--sm draft-btn--danger"
                  disabled={savingPatch || committing || deleting} onClick={() => void handleDeleteDraft()}>
                  {t(deleting ? '正在删除草稿…' : '删除草稿')}
                </button>}
              </div>
            </header>

            <div className="draft-detail-scroll">
              {actionError ? (
                <div className="draft-notice draft-notice--error" role="alert">{actionError}</div>
              ) : null}
              {notice ? (
                <div className="draft-notice draft-notice--info" role="status">{notice}</div>
              ) : null}

              {/* Quality Audit Summary Banner */}
              <section
                className={`draft-audit-banner ${audit.gate_passed ? 'is-passed' : 'is-blocked'}`}
                aria-label={t('检查结果')}
              >
                <div className="draft-audit-banner__top">
                  <div className="draft-audit-banner__status">
                    <strong>
                      {audit.gate_passed ? t('✓ 自动检查通过') : t('需人工核对')}
                    </strong>
                    <span>
                      {audit.gate_passed
                        ? t('全部台词均已通过漏译、假名残留与语速预算检查，可直接确认合成并交付。')
                        : t('检测到需复核的翻译或语速预警项；可在下方表格修订台词并保存，以实时刷新质检结果。')}
                    </span>
                  </div>
                  <span style={{ fontSize: 11.5, color: 'var(--muted-strong)', fontWeight: 600 }}>
                    {formatMessage('语速预算 {0} 字/秒 · 上限 {1}x', [audit.chars_per_second, audit.max_atempo])}
                  </span>
                </div>

                <div className="draft-audit-metrics">
                  <div className="draft-audit-metric">
                    <span>{t('已译台词')}</span>
                    <b>{translatedCount}/{totalCueCount}</b>
                  </div>
                  <div className={`draft-audit-metric ${audit.untranslated_indices.length > 0 ? 'is-alert-error' : ''}`}>
                    <span>{t('漏译句数')}</span>
                    <b data-metric="untranslated">{audit.untranslated_indices.length}</b>
                  </div>
                  <div className={`draft-audit-metric ${audit.japanese_residue_indices.length > 0 ? 'is-alert-warn' : ''}`}>
                    <span>{t('假名残留')}</span>
                    <b data-metric="japanese-residue">{audit.japanese_residue_indices.length}</b>
                  </div>
                  <div className={`draft-audit-metric ${audit.over_speed_cues.length > 0 ? 'is-alert-warn' : ''}`}>
                    <span>{t('语速超限')}</span>
                    <b data-metric="over-speed">{audit.over_speed_cues.length}</b>
                  </div>
                </div>

                {audit.script_alignment && (
                  <ul className="draft-audit-warnings-list">
                    {audit.script_alignment.unmatched.map(row => <li key={row.line}>
                      {formatMessage('台本第 {0} 行未匹配', [row.line])} · {row.text}
                    </li>)}
                    {audit.script_alignment.low_confidence.map(row => <li key={row.cue_id}>
                      {formatMessage('台本第 {0} 行的时间锚点需复核', [row.line])} · {row.cue_id}
                    </li>)}
                    {audit.script_alignment.extra_cue_ids.length > 0 && <li>
                      {t('未匹配台本的录音片段')} · {audit.script_alignment.extra_cue_ids.join(', ')}
                    </li>}
                    {audit.script_alignment.conflicts.map((message, i) => <li key={i}>{message}</li>)}
                  </ul>
                )}
                {audit.warnings.length > 0 ? (
                  <ul className="draft-audit-warnings-list">
                    {audit.warnings.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                ) : null}

                {(referenceCandidate || sampleTakes.length > 0 || mixedAudioPath) ? (
                  <div className="draft-audition-bar">
                    <span className="draft-audition-label">{t('音频试听：')}</span>
                    {referenceCandidate ? (
                      <button
                        type="button"
                        className="draft-btn draft-btn--sm"
                        onClick={() => {
                          playClipInAudioBar(
                            playerActions,
                            referenceCandidate.path,
                            formatMessage('{0} · 克隆参考干声', [selectedDraft.title || selectedDraft.draft_id]),
                          )
                        }}
                      >
                        {referenceCandidate.snr_db !== undefined
                          ? formatMessage('▶ 试听克隆参考干声 ({0}s · SNR {1}dB)', [
                              (referenceCandidate.duration ?? 0).toFixed(1),
                              referenceCandidate.snr_db.toFixed(1),
                            ])
                          : t('▶ 试听克隆参考干声')}
                      </button>
                    ) : null}
                    {sampleTakes.map((take) => (
                      <button
                        key={`${take.cue_id}-${take.index}`}
                        type="button"
                        className="draft-btn draft-btn--sm"
                        title={take.text}
                        onClick={() => {
                          playClipInAudioBar(
                            playerActions,
                            resolveSampleTakeAudioSrc(take),
                            formatMessage('{0} · 样音 #{1}', [selectedDraft.title || selectedDraft.draft_id, take.index + 1]),
                          )
                        }}
                      >
                        {formatMessage('▶ 试听样音 #{0} ({1}s)', [take.index + 1, (take.duration ?? 0).toFixed(1)])}
                      </button>
                    ))}
                    {mixedAudioPath ? (
                      <button
                        type="button"
                        className="draft-btn draft-btn--sm"
                        onClick={() => {
                          playClipInAudioBar(
                            playerActions,
                            mixedAudioPath,
                            formatMessage('{0} · 成品配音混音', [selectedDraft.title || selectedDraft.draft_id]),
                          )
                        }}
                      >
                        {t('▶ 试听成品混音')}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </section>

              {/* Segment Review Table */}
              <section className="draft-segments-section" aria-label={t('台词复核列表')}>
                <div className="draft-segments-toolbar">
                  <div className="draft-filter-tabs" role="group" aria-label={t('台词筛选')}>
                    <button
                      type="button"
                      className="draft-filter-tab"
                      aria-pressed={filterMode === 'all'}
                      onClick={() => setFilterMode('all')}
                    >
                      <span>{t('全部台词')}</span>
                      <small>{totalCueCount}</small>
                    </button>
                    <button
                      type="button"
                      className="draft-filter-tab"
                      aria-pressed={filterMode === 'warnings'}
                      onClick={() => setFilterMode('warnings')}
                    >
                      <span>{t('仅看预警项')}</span>
                      <small>{warningCueCount}</small>
                    </button>
                  </div>

                  <div className="draft-save-bar">
                    {pendingPatch.edits.length > 0 ? (
                      <>
                        <span className="draft-dirty-pill">
                          {formatMessage('待保存 {0} 处修改', [pendingPatch.edits.length])}
                        </span>
                        <button
                          type="button"
                          className="draft-btn draft-btn--sm"
                          disabled={savingPatch || committing}
                          onClick={() => { setEditedTranslations({}); setEditedDeliveries({}) }}
                        >
                          {t('放弃未存修改')}
                        </button>
                      </>
                    ) : null}
                    <button
                      type="button"
                      className="draft-btn draft-btn--primary"
                      disabled={pendingPatch.edits.length === 0 || savingPatch || committing || isBusyState}
                      onClick={() => { void handleSaveEdits() }}
                    >
                      {savingPatch ? t('正在保存修订…') : t('保存修订')}
                    </button>
                  </div>
                </div>

                {visibleSegments.length === 0 ? (
                  <div className="draft-empty-state" style={{ minHeight: 140 }}>
                    {filterMode === 'warnings'
                      ? t('当前没有触发预警的台词条目。')
                      : t('当前草稿暂无台词条目。')}
                  </div>
                ) : (
                  <div className="draft-table-wrap">
                    <table className="draft-segments-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>{t('时间区间')}</th>
                          <th>{t('原文')}</th>
                          <th>{t('译文修订')}</th>
                          <th>{t('发声与操作')}</th>
                          <th>{t('质检状态')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleSegments.map((seg, rowIdx) => {
                          const segIndex = typeof seg.index === 'number' ? seg.index : rowIdx
                          const warn = segmentWarnings.get(segIndex)
                          const currentVal = editedTranslations[segIndex] ?? seg.translation ?? ''
                          const isDirty = editedTranslations[segIndex] !== undefined && editedTranslations[segIndex] !== (seg.translation ?? '')
                          const currentDelivery = editedDeliveries[segIndex] ?? seg.delivery ?? 'normal'
                          const cueId = seg.cue_id || ''
                          const markedRetake = Boolean(cueId && retakeCueIds.includes(cueId))
                          return (
                            <tr
                              key={seg.cue_id || segIndex}
                              data-cue-index={segIndex}
                              className={warn?.hasWarning ? 'has-warning' : ''}
                            >
                              <td className="draft-cue-index">
                                <div>#{segIndex + 1}</div>
                                <small>{seg.cue_id}</small>
                              </td>
                              <td className="draft-cue-time">
                                <span>{formatCueTimeRange(seg.start, seg.end)}</span>
                                {primaryTrackPath ? (
                                  <button
                                    type="button"
                                    className="draft-btn draft-btn--sm"
                                    style={{ width: 'fit-content' }}
                                    onClick={() => {
                                      playClipInAudioBar(
                                        playerActions,
                                        primaryTrackPath,
                                        formatMessage('{0} · #{1}', [selectedDraft.title || selectedDraft.draft_id, segIndex + 1]),
                                        seg.start,
                                      )
                                    }}
                                  >
                                    {t('▶ 原声定位')}
                                  </button>
                                ) : null}
                              </td>
                              <td className="draft-cue-source">{seg.source_text || '—'}</td>
                              <td className="draft-cue-translation">
                                <input
                                  type="text"
                                  className={`draft-translation-input ${isDirty ? 'is-dirty' : ''}`}
                                  aria-label={formatMessage('修订第 {0} 句译文', [segIndex + 1])}
                                  placeholder={t('输入目标语言译文…')}
                                  value={currentVal}
                                  disabled={savingPatch || committing || isBusyState}
                                  onChange={(event) => {
                                    const nextValue = event.target.value
                                    setEditedTranslations((prev) => ({
                                      ...prev,
                                      [segIndex]: nextValue,
                                    }))
                                  }}
                                />
                              </td>
                              <td>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                  <select
                                    aria-label={formatMessage('第 {0} 句发声风格', [segIndex + 1])}
                                    value={currentDelivery}
                                    disabled={savingPatch || committing || isBusyState}
                                    onChange={(event) => {
                                      const val = event.target.value
                                      setEditedDeliveries((prev) => ({ ...prev, [segIndex]: val }))
                                    }}
                                    style={{ padding: '4px 6px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)', fontSize: 12 }}
                                  >
                                    <option value="normal">{t('普通')}</option>
                                    <option value="soft">{t('轻柔')}</option>
                                    <option value="whisper">{t('耳语')}</option>
                                  </select>
                                  {selectedDraft.state === 'completed' && cueId ? (
                                    <button
                                      type="button"
                                      className={`draft-btn draft-btn--sm${markedRetake ? ' draft-btn--primary' : ''}`}
                                      disabled={savingPatch || committing || isBusyState}
                                      onClick={() => {
                                        setRetakeCueIds((prev) => (
                                          prev.includes(cueId) ? prev.filter((id) => id !== cueId) : [...prev, cueId]
                                        ))
                                      }}
                                    >
                                      {markedRetake ? t('✓ 已标记重抽') : t('标记单句重抽')}
                                    </button>
                                  ) : null}
                                </div>
                              </td>
                              <td>
                                <div className="draft-warning-badges">
                                  {warn?.untranslated ? (
                                    <span className="draft-badge draft-badge--error">{t('漏译')}</span>
                                  ) : null}
                                  {warn?.japaneseResidue ? (
                                    <span className="draft-badge draft-badge--warn">{t('假名残留')}</span>
                                  ) : null}
                                  {warn?.blockingEmpty ? (
                                    <span className="draft-badge draft-badge--error">{t('无有效译文')}</span>
                                  ) : null}
                                  {warn?.overSpeed ? (
                                    <>
                                      <span className="draft-badge draft-badge--warn">
                                        {formatMessage('预计倍速 {0}x', [warn.overSpeed.predicted_atempo.toFixed(2)])}
                                      </span>
                                      <span className="draft-badge draft-badge--muted">
                                        {formatMessage('借静默 +{0}s', [warn.overSpeed.available_slack.toFixed(2)])}
                                      </span>
                                      <span className="draft-badge draft-badge--muted">
                                        {formatMessage('建议 ≤{0} 字', [warn.overSpeed.max_recommended_chars])}
                                      </span>
                                    </>
                                  ) : null}
                                  {!warn?.hasWarning ? (
                                    <span className="draft-badge draft-badge--ok">{t('正常')}</span>
                                  ) : null}
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {/* Approve & Render Commit Card */}
              <section className="draft-commit-card" aria-label={t('确认合成并交付')}>
                <h3>{t('确认合成并交付')}</h3>
                <div className="draft-commit-grid">
                  <label className="draft-field">
                    <span>{t('交付输出目录')}</span>
                    <input
                      type="text"
                      aria-label={t('交付输出目录')}
                      value={outputDir}
                      placeholder={defaultCommitOutputDir(selectedDraft.work_dir)}
                      disabled={committing || savingPatch || isBusyState}
                      onChange={(event) => setOutputDir(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    className="draft-btn draft-btn--primary"
                    style={{ minHeight: 36, padding: '0 16px' }}
                    disabled={
                      committing ||
                      savingPatch ||
                      isBusyState ||
                      selectedDraft.segments.length === 0 ||
                      !outputDir.trim()
                    }
                    onClick={() => { void handleCommitDraft() }}
                  >
                    {committing
                      ? t('正在合成并交付…')
                      : retakeCueIds.length > 0
                        ? formatMessage('重抽 {0} 句并重新混音', [retakeCueIds.length])
                        : selectedDraft.state === 'completed'
                          ? t('重新合成并交付')
                          : t('确认合成并交付')}
                  </button>
                </div>

                <div className="draft-commit-options">
                  <label className="draft-checkbox">
                    <input
                      type="checkbox"
                      checked={exportSrt}
                      disabled={committing || savingPatch || isBusyState}
                      onChange={(event) => setExportSrt(event.target.checked)}
                    />
                    <span>SRT</span>
                  </label>
                  <label className="draft-checkbox">
                    <input
                      type="checkbox"
                      checked={exportLrc}
                      disabled={committing || savingPatch || isBusyState}
                      onChange={(event) => setExportLrc(event.target.checked)}
                    />
                    <span>LRC</span>
                  </label>
                  <label className="draft-checkbox">
                    <input
                      type="checkbox"
                      checked={bilingual}
                      disabled={committing || savingPatch || isBusyState}
                      onChange={(event) => setBilingual(event.target.checked)}
                    />
                    <span>{t('双语字幕')}</span>
                  </label>
                  <label className="draft-checkbox">
                    <input
                      type="checkbox"
                      checked={enableDubbing}
                      disabled={committing || savingPatch || isBusyState}
                      onChange={(event) => setEnableDubbing(event.target.checked)}
                    />
                    <span>{t('启用配音混音')}</span>
                  </label>
                </div>

                {enableDubbing ? (
                  <details style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                    <summary style={{ cursor: 'pointer', fontSize: 12.5, fontWeight: 600, color: 'var(--muted-strong)' }}>
                      {t('ASMR 双耳与混音选项（V2）')}
                    </summary>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', marginTop: 10 }}>
                      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
                        <span>{t('双耳声像')}</span>
                        <select
                          value={binauralMode}
                          disabled={committing || savingPatch || isBusyState}
                          onChange={(e) => setBinauralMode(e.target.value as 'dynamic_hrtf' | 'static' | 'off')}
                          style={{ padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)', fontSize: 12.5 }}
                        >
                          <option value="dynamic_hrtf">{t('动态双耳 HRTF（推荐）')}</option>
                          <option value="static">{t('逐句静态声像')}</option>
                          <option value="off">{t('单声道')}</option>
                        </select>
                      </label>
                      <label className="draft-checkbox">
                        <input
                          type="checkbox"
                          checked={sidechainDucking}
                          disabled={committing || savingPatch || isBusyState}
                          onChange={(e) => setSidechainDucking(e.target.checked)}
                        />
                        <span>{t('配音发声时侧链压低背景')}</span>
                      </label>
                      <label className="draft-checkbox">
                        <input
                          type="checkbox"
                          checked={roomToneInpaint}
                          disabled={committing || savingPatch || isBusyState}
                          onChange={(e) => setRoomToneInpaint(e.target.checked)}
                        />
                        <span>{t('填补分离背景底噪空洞')}</span>
                      </label>
                    </div>
                  </details>
                ) : null}

                {selectedDraft.state === 'completed' && selectedDraft.artifacts?.output_dir ? (
                  <div className="draft-delivered-box">
                    <strong>{t('最近交付产物')}</strong>
                    <div>{t('输出目录：')}{displayPath(selectedDraft.artifacts.output_dir)}</div>
                    {selectedDraft.artifacts.subtitles
                      ? Object.entries(selectedDraft.artifacts.subtitles).map(([fmt, subPath]) => (
                          <div key={fmt}>{fmt.toUpperCase()}: {displayPath(subPath)}</div>
                        ))
                      : null}
                    {selectedDraft.artifacts.dubbing ? (
                      <div>
                        {formatMessage('配音混音：{0}（复用缓存 {1} 句 · 新合成 {2} 句）', [
                          displayPath(selectedDraft.artifacts.dubbing.mixed_audio_path || ''),
                          selectedDraft.artifacts.dubbing.reused_take_count ?? 0,
                          selectedDraft.artifacts.dubbing.synthesized_take_count ?? 0,
                        ])}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </section>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
