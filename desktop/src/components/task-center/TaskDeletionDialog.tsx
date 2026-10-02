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
        throw new Error('删除预览与所选任务不一致，请重新预览。')
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
        throw new Error('删除结果归属不匹配，请刷新任务状态核对；未按未知结果移除本地记录。')
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
    <header><h2 id="tc-delete-title">{result ? '删除结果' : '删除任务历史'}</h2>
      <button type="button" className="tc-action" disabled={executing} onClick={onClose} aria-label="关闭删除面板">关闭</button></header>
    <div className="tc-delete-body">
      {!result && <>
        <p>本次选择 <strong>{taskIds.length}</strong> 项任务。只处理以下所选记录，不删除整个批次；运行中或待处理的任务不可删除。</p>
        <fieldset disabled={executing}><legend>删除方式</legend>{(Object.keys(modes) as TaskDeletionMode[]).map(value =>
          <label key={value}><input type="radio" name="task-deletion-mode" value={value} checked={mode === value}
            onChange={() => { setPreview(null); setMode(value) }} /><span>{modes[value]}</span></label>)}</fieldset>
        <p className="tc-delete-note">{mode === 'history_only' ? '保留所有文件，仅移除历史记录和关联记录。' : '仅删除预览中明确标为“将删除”的独占附带文件；输入素材、音色库引用、共享或未登记文件以及目录均保留，不会清空整个任务目录。'}</p>
        {loading && <p role="status">正在检查所选任务与文件…</p>}
        {current && !loading && <>
          <p className="tc-delete-summary">可删除 {current.summary.eligible_count} 项 · 不可删除 {current.summary.blocked_count} 项<br />
            将删除 {current.summary.delete_file_count} 个文件（{bytes(current.summary.delete_bytes)}）· 保留 {current.summary.retain_file_count} 个文件</p>
          <p>批次范围：{batchIds.length ? `${batchIds.length} 个批次中的所选任务` : '无关联批次'}。<br />{batchIds.map(id => <code key={id}>{id} </code>)}</p>
          {current.tasks.map(task => <details key={task.task_id} open={!task.eligible} className="tc-delete-item">
            <summary><code>{task.task_id}</code> · {task.eligible ? '可删除' : '不可删除'} · {task.files.length} 个关联文件</summary>
            <p>批次：{task.batch_ids.join('、') || '无'}{task.reason ? ` · ${task.reason}` : ''}</p>
            {task.files.length ? <ul>{task.files.map((file, index) => <li key={`${file.path}-${index}`}>
              <strong>{file.action === 'delete' ? '将删除' : '保留'}</strong><code>{file.path}</code>
              {file.reason && <span>{file.reason}</span>}</li>)}</ul> : <p>没有关联文件。</p>}
          </details>)}
          {!current.can_execute && <p className="tc-delete-error" role="alert">本次选择含不可删除的任务，请关闭面板并调整选择；不会取消或跳过这些任务后继续删除。</p>}
          {expired && <p className="tc-delete-error" role="alert">预览已过期，请重新预览。</p>}
          <p className="tc-delete-note">确认后不可在应用内撤销。预览有效至 {new Date(current.expires_at).toLocaleTimeString()}。</p>
        </>}
      </>}
      {result && <>
        <p className="tc-delete-summary">{modes[result.mode]}：已删除历史 {result.results.filter(item => item.history_deleted).length} 项 · 部分完成 {result.summary.partial_count} 项 · 未删除或失败 {result.summary.blocked_count + result.summary.failed_count} 项</p>
        <p>文件：删除 {result.summary.deleted_file_count} · 保留 {result.summary.retained_file_count} · 失败 {result.summary.failed_file_count}</p>
        {result.results.map(item => <details key={item.task_id} className="tc-delete-item" open={item.status !== 'deleted'}>
          <summary><code>{item.task_id}</code> · {outcomes[item.status]} · 历史{item.history_deleted ? '已删除' : '仍保留'}</summary>
          {item.reason && <p>{item.reason}</p>}
          <ul>{item.files.map((file, index) => <li key={`${file.path}-${index}`}><strong>{fileOutcomes[file.status]}</strong><code>{file.path}</code>{file.reason && <span>{file.reason}</span>}</li>)}</ul>
        </details>)}
      </>}
      {error && <p className="tc-delete-error" role="alert">{error}</p>}
    </div>
    <footer>{result ? <button type="button" className="tc-action" onClick={onClose}>完成</button> : <>
      <button type="button" className="tc-action" disabled={executing} onClick={onClose}>取消</button>
      <button type="button" className="tc-action" disabled={loading || executing} onClick={() => setGeneration(value => value + 1)}>重新预览</button>
      <button type="button" className="tc-action tc-danger" disabled={loading || executing || expired || !current?.can_execute}
        onClick={() => void execute()}>{executing ? '正在删除…' : `确认${modes[mode]}（${current?.summary.eligible_count ?? 0} 项）`}</button>
    </>}</footer>
  </dialog>
}
