import { useEffect, useState } from 'react'
import { subtitlesApi } from '@/api/subtitles'
import { tasksApi } from '@/api/tasks'
import type { ScriptReview, SubtitleSegmentModel } from '@/api/types'
import { useTaskStore } from '@/stores/taskStore'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { t } from '@/i18n'

export default function ScriptSubtitleReview({ taskId, onEdit }: {
  taskId: string
  onEdit: (entries: SubtitleSegmentModel[], path: string, audio: string, needsReview: boolean, duration: number | null, review: ScriptReview) => void
}) {
  const [review, setReview] = useState<ScriptReview | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const player = useAudioPlayerStore()
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    setReview(null); setError(''); setAcknowledged(false)
    if (!taskId) { setStatus(''); return }
    const refresh = async () => {
      try {
        const task = await tasksApi.get(taskId)
        if (!active) return
        setStatus(task.message || task.state)
        const store = useTaskStore.getState()
        const local = store.tasks.find(item => item.serverTaskId === taskId)
        if (local) store.updateTask(local.id, { status: task.state as typeof local.status,
          progress: Math.round(task.progress * 100), message: task.message, stage: task.stage || undefined })
        if (['completed', 'failed', 'cancelled'].includes(task.state)) {
          const result = await subtitlesApi.scriptReview(taskId)
          if (!active) return
          setReview(result.review)
          if (task.state !== 'completed') setError(task.detail || task.message || t('任务未完成'))
        } else timer = setTimeout(() => void refresh(), 2000)
      } catch (e) {
        if (active) setError(String(e))
      }
    }
    void refresh()
    return () => { active = false; if (timer) clearTimeout(timer) }
  }, [taskId])
  const entries = review?.complete ? review.entries : review?.draft_entries || []
  const playable = (cue: SubtitleSegmentModel) => Number.isFinite(cue.start) && cue.start >= 0 && Number.isFinite(cue.end) && cue.end > cue.start
  const editReady = !!entries.length && entries.every(playable)
  return <section style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 8 }} aria-label={t('台本匹配核对')}>
    <h3>{t('台本匹配核对')}</h3>
    {!taskId && <p>{t('提交后在此查看结果，也可在任务中心查看进度。')}</p>}
    {status && <p role="status">{status}</p>}
    {error && <p role="alert">{error}</p>}
    {taskId && !review && error && <button onClick={() => void subtitlesApi.scriptReview(taskId).then(r => setReview(r.review)).catch(e => setError(String(e)))}>{t('重新读取核对报告')}</button>}
    {review && <>
      <p>{t('时间来自录音字幕片段，未进行逐字强制对齐。')}{review.complete ? t('全部台词已匹配，导出前请试听。') : t('仍有待核对项，未导出字幕。')}</p>
      <p>{t('已匹配')} {review.entries.length} · {t('未匹配')} {review.unmatched.length} · {t('额外录音片段')} {review.extra_asr.length}</p>
      {review.conflicts.map((item, i) => <p key={i} role="alert">{item}</p>)}
      {!!review.unmatched.length && <details open><summary>{t('未匹配台词（没有时间，不会自动插入）')}</summary><ol>{review.unmatched.map(item => <li key={item.script_idx}>{item.script_idx + 1}. {item.text}</li>)}</ol></details>}
      {!!review.extra_asr.length && <details open><summary>{t('额外录音片段')}</summary>{review.extra_asr.map(item => <p key={item.asr_idx}>{item.start.toFixed(2)}–{item.end.toFixed(2)} {item.text}</p>)}</details>}
      {!!entries.length && <div style={{ maxHeight: 320, overflow: 'auto' }}><table style={{ width: '100%', textAlign: 'left' }}><thead><tr><th>{t('开始')}</th><th>{t('结束')}</th><th>{review.complete ? t('确认台词') : t('录音原文草稿')}</th><th>{t('试听')}</th></tr></thead><tbody>{entries.map((cue, i) => <tr key={i}><td>{cue.start.toFixed(2)}</td><td>{cue.end.toFixed(2)}</td><td>{cue.text}</td><td>{review.audio_path && playable(cue) && <button onClick={() => {
        if (player.src !== review.audio_path) player.show(review.audio_path!, t('台本录音'))
        player.seek(cue.start)
      }}>{t('定位')}</button>}</td></tr>)}</tbody></table></div>}
      {!review.complete && <label style={{ display: 'block', margin: '12px 0' }}><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} />{t('我会按录音核对漏读和额外内容；未匹配台词不会自动加入草稿。')}</label>}
      <button disabled={!editReady || (!review.complete && !acknowledged)} onClick={() => onEdit(entries, review.output_path, review.audio_path || '', !review.complete, review.duration ?? null, review)}>{t('载入字幕编辑器试听修正')}</button>
    </>}
  </section>
}
