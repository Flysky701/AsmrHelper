import { useEffect, useState } from 'react'
import { useReferenceField, useReferenceSessionStore, startReferenceTranscription } from '@/stores/referenceSessionStore'
import { tasksApi } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'
import { sameClip } from './referencePlayback'

type Props = { path: string; start: number; end: number; language: string; transcript: string; valid: boolean; onResult: (text: string) => void }
const terminal = (task: TaskStatusResponse) => ['completed', 'failed', 'cancelled', 'skipped'].includes(task.state)

export default function ClipTranscription(props: Props) {
  const [task, setTask] = useReferenceField('clipTask')
  const [submitting] = useReferenceField('clipSubmitting')
  const [error, setError] = useReferenceField('clipError')
  const [note, setNote] = useReferenceField('clipNote')
  const [, setRetry] = useReferenceField('clipRetry')
  const [disconnected, setDisconnected] = useReferenceField('clipDisconnected')
  const [result, setResult] = useReferenceField('clipResult')
  const [now, setNow] = useState(Date.now())
  const running = !!task && !terminal(task)
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const elapsed = task ? Math.max(0, Math.floor(((task.finished_at ? Date.parse(task.finished_at) : now) - Date.parse(task.started_at || task.created_at)) / 1000)) : 0
  const stateLabels: Record<string, string> = { pending: '等待识别', running: '正在识别', completed: '选段识别完成', failed: '识别失败', cancelled: '已取消', skipped: '已跳过' }
  const start = startReferenceTranscription
  async function cancel() {
    if (!task) return
    const source = useReferenceSessionStore.getState().source
    try {
      const status = await tasksApi.cancel(task.task_id)
      if (useReferenceSessionStore.getState().source === source && useReferenceSessionStore.getState().clipTask?.task_id === task.task_id) setTask(status)
    } catch (cause) { if (useReferenceSessionStore.getState().source === source) setError(String(cause)) }
  }
  return <div className="reference-clip-asr">
    <div className="row"><button disabled={!props.valid || submitting || running} onClick={() => void start()}>{submitting ? '正在提交…' : running ? '正在识别选段…' : '识别选段原文'}</button><span className="muted">仅识别框选的 {Math.max(0, props.end - props.start).toFixed(1)} 秒，不读取字幕。</span></div>
    {task && <div className="reference-analysis-status" role="status"><div className="row spread"><span>{terminal(task) ? stateLabels[task.state] : task.message || stateLabels[task.state]}</span>{running && <button onClick={() => void cancel()}>取消识别</button>}</div><progress max={1} value={task.progress} aria-label="选段识别进度" /><p className="muted">阶段进度 {Math.round(task.progress * 100)}% · 已用时 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒</p>{running && <p className="muted">模型首次加载可能较慢；此处显示阶段进度，可继续试听。切换录音后可在任务中心查看任务。</p>}</div>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {disconnected && <div className="row"><button onClick={() => setRetry(value => value + 1)}>重新获取识别进度</button><button onClick={() => { setTask(null); setDisconnected(false); setNote('已结束跟踪，原任务可能仍在运行，可在任务中心查看。') }}>结束跟踪</button></div>}
    {note && <p className="muted" role="status">{note}</p>}
    {result && <div className="notice"><p>{result.text}</p><button disabled={!sameClip(result.snapshot, props)} onClick={() => { props.onResult(result.text); setResult(null); setNote('已填入原文，请试听核对。') }}>使用识别结果</button>{!sameClip(result.snapshot, props) && <p>返回识别时的选段和语言后可填入，或重新识别当前选段。</p>}</div>}
  </div>
}
