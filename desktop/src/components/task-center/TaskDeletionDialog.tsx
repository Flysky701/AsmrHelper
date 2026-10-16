import { t, format as formatMessage, useI18n } from '@/i18n'
import { displayPath } from '@/utils/displayPath'
import { useEffect, useRef, useState } from 'react'
import { tasksApi } from '@/api/tasks'
import type { TaskDeletionExecuteResponse, TaskDeletionMode, TaskDeletionPreviewResponse } from '@/api/types'

const modes = { history_only: '仅删除历史', history_and_files: '删除历史及附带文件' }
const outcomes = { deleted: '已删除', blocked: '未删除', failed: '删除失败', partial: '部分完成' }
const fileOutcomes = { deleted: '已删除', retained: '已保留', failed: '删除失败' }
const bytes = (value: number) => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`

export default function TaskDeletionDialog({ taskIds, onDeleted, onClose }: {
  taskIds: string[]
  onDeleted: (taskIds: string[]) => void
  onClose: () => void
}) {
  useI18n()
  const dialog = useRef<HTMLDialogElement>(null)
  const submitting = useRef(false)
  const [mode, setMode] = useState<TaskDeletionMode>('history_only')
  const [generation, setGeneration] = useState(0)
  const [preview, setPreview] = useState<TaskDeletionPreviewResponse | null>(null)
  const [result, setResult] = useState<TaskDeletionExecuteResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [executing, setExecuting] = useState(false)
  const [error, setError] = useState('')
  const [expired, setExpired] = useState(false)

  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])

  useEffect(() => {
    let disposed = false
    setLoading(true)
    setPreview(null)
    setError('')
    setExpired(false)
    tasksApi.deletionPreview(taskIds, mode).then(response => {
      if (disposed) return
      const received = new Set(response.tasks.map(task => task.task_id))
      if (response.mode !== mode || response.tasks.length !== taskIds.length || received.size !== taskIds.length || taskIds.some(id => !received.has(id))) {
        throw new Error("删除预览与所选任务不一致，请重新预览。")
      }
      setPreview(response)
    }).catch(cause => { if (!disposed) setError(cause instanceof Error ? cause.message : String(cause)) })
      .finally(() => { if (!disposed) setLoading(false) })
    return () => { disposed = true }
  }, [taskIds, mode, generation])

  useEffect(() => {
    if (!preview) return
    const delay = Date.parse(preview.expires_at) - Date.now()
    if (!Number.isFinite(delay) || delay <= 0) { setExpired(true); return }
    const timer = setTimeout(() => setExpired(true), Math.min(delay, 2147483647))
    return () => clearTimeout(timer)
  }, [preview])

  const execute = async () => {
    if (submitting.current || loading || expired || !preview?.can_execute || preview.mode !== mode || result) return
    if (!Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= Date.now()) { setExpired(true); return }
    submitting.current = true
    setExecuting(true)
    setError('')
    try {
      const response = await tasksApi.deletionExecute(preview.preview_id)
      if (response.preview_id !== preview.preview_id || response.mode !== mode || response.results.length !== taskIds.length
        || new Set(response.results.map(item => item.task_id)).size !== taskIds.length
        || response.results.some(item => !taskIds.includes(item.task_id))) {
        throw new Error("删除结果归属不匹配，请刷新任务状态核对；未按未知结果移除本地记录。")
      }
      setResult(response)
      onDeleted(response.results.filter(item => item.history_deleted).map(item => item.task_id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      // The same preview may be retried safely: the backend returns its stored result.
    } finally {
      submitting.current = false
      setExecuting(false)
    }
  }
  const current = preview?.mode === mode ? preview : null
  const batchIds = [...new Set(current?.tasks.flatMap(task => task.batch_ids) ?? [])]
  return <dialog ref={dialog} className="tc-delete-dialog" aria-labelledby="tc-delete-title"
    onCancel={event => { event.preventDefault(); if (!executing) onClose() }}>
    <header><h2 id="tc-delete-title">{result ? t("删除结果") : t("删除任务历史")}</h2>
      <button type="button" className="tc-action" disabled={executing} onClick={onClose} aria-label={t("关闭删除面板")}>{t("关闭")}</button></header>
    <div className="tc-delete-body">
      {!result && <>
        <p>{t("本次选择")} <strong>{taskIds.length}</strong> {t("项任务（仅处理所选记录，不删除整个批次）。")}</p>
        <fieldset disabled={executing}><legend>{t("删除方式")}</legend>{(Object.keys(modes) as TaskDeletionMode[]).map(value =>
          <label key={value}><input type="radio" name="task-deletion-mode" value={value} checked={mode === value}
            onChange={() => { setPreview(null); setMode(value) }} /><span>{t(modes[value])}</span></label>)}</fieldset>
        <p className="tc-delete-note">{mode === 'history_only' ? t("保留所有文件，仅移除历史记录。") : t("仅删除标为“将删除”的独占附带文件；输入素材、音色库引用与共享文件均保留。")}</p>
        {loading && <p role="status">{t("正在检查所选任务与文件…")}</p>}
        {current && !loading && <>
          <p className="tc-delete-summary">{t("可删除")}{current.summary.eligible_count} {t("项 · 不可删除")}{current.summary.blocked_count} {t("项")}<br />
            {t("将删除")}{current.summary.delete_file_count} {t("个文件（")}{bytes(current.summary.delete_bytes)}{t("）· 保留")}{current.summary.retain_file_count} {t("个文件")}</p>
          {batchIds.length > 0 && <p>{t("批次范围：")}{formatMessage("{0} 个批次中的所选任务", [batchIds.length])}（{batchIds.map(id => <code key={id}>{id} </code>)}）</p>}
          {current.tasks.map(task => <details key={task.task_id} open={!task.eligible} className="tc-delete-item">
            <summary><code>{task.task_id}</code> · {task.eligible ? t("可删除") : t("不可删除")} · {task.files.length} {t("个关联文件")}</summary>
            <p>{t("批次：")}{task.batch_ids.join('、') || t("无")}{task.reason ? ` · ${task.reason}` : ''}</p>
            {task.files.length ? <ul>{task.files.map((file, index) => <li key={`${file.path}-${index}`}>
              <strong>{file.action === 'delete' ? t("将删除") : t("保留")}</strong><code>{displayPath(file.path)}</code>
              {file.reason && <span>{file.reason}</span>}</li>)}</ul> : <p>{t("没有关联文件。")}</p>}
          </details>)}
          {!current.can_execute && <p className="tc-delete-error" role="alert">{t("所选任务含不可删除项，请关闭面板并调整选择。")}</p>}
          {expired && <p className="tc-delete-error" role="alert">{t("预览已过期，请重新预览。")}</p>}
          <p className="tc-delete-note">{t("预览有效至")} {new Date(current.expires_at).toLocaleTimeString()}。</p>
        </>}
      </>}
      {result && <>
        <p className="tc-delete-summary">{t(modes[result.mode])}{t("：已删除历史")}{result.results.filter(item => item.history_deleted).length} {t("项 · 部分完成")}{result.summary.partial_count} {t("项 · 未删除或失败")}{result.summary.blocked_count + result.summary.failed_count} {t("项")}</p>
        <p>{t("文件：删除")}{result.summary.deleted_file_count} {t("· 保留")}{result.summary.retained_file_count} {t("· 失败")}{result.summary.failed_file_count}</p>
        {result.results.map(item => <details key={item.task_id} className="tc-delete-item" open={item.status !== 'deleted'}>
          <summary><code>{item.task_id}</code> · {t(outcomes[item.status])} {t("· 历史")}{item.history_deleted ? t("已删除") : t("仍保留")}</summary>
          {item.reason && <p>{item.reason}</p>}
          <ul>{item.files.map((file, index) => <li key={`${file.path}-${index}`}><strong>{t(fileOutcomes[file.status])}</strong><code>{displayPath(file.path)}</code>{file.reason && <span>{file.reason}</span>}</li>)}</ul>
        </details>)}
      </>}
      {error && <p className="tc-delete-error" role="alert">{t(error)}</p>}
    </div>
    <footer>{result ? <button type="button" className="tc-action" onClick={onClose}>{t("完成")}</button> : <>
      <button type="button" className="tc-action" disabled={executing} onClick={onClose}>{t("取消")}</button>
      <button type="button" className="tc-action" disabled={loading || executing} onClick={() => setGeneration(value => value + 1)}>{t("重新预览")}</button>
      <button type="button" className="tc-action tc-danger" disabled={loading || executing || expired || !current?.can_execute}
        onClick={() => void execute()}>{executing ? t("正在删除…") : formatMessage("确认{0}（{1} 项）", [t(modes[mode]), current?.summary.eligible_count ?? 0])}</button>
    </>}</footer>
  </dialog>
}
