import { useEffect, useRef, useState } from 'react'
import { speechApi } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'
import { sameClip } from './referencePlayback'

type Props = { path: string; start: number; end: number; language: string; transcript: string; valid: boolean; onResult: (text: string) => void }
const terminal = (task: TaskStatusResponse) => ['completed', 'failed', 'cancelled', 'skipped'].includes(task.state)

export default function ClipTranscription(props: Props) {
  const [task, setTask] = useState<TaskStatusResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [retry, setRetry] = useState(0)
  const [disconnected, setDisconnected] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [result, setResult] = useState<{ text: string; snapshot: Props } | null>(null)
  const latest = useRef(props)
  latest.current = props
  const request = useRef<Props | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!task?.task_id) return
    const id = task.task_id
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    let failures = 0
    setDisconnected(false)
    async function poll() {
      try {
        const response = await speechApi.transcriptionStatus(id)
        if (stopped) return
        failures = 0; setTask(response.status); setError('')
        if (response.status.state === 'completed') {
          const text = response.result?.transcript?.trim()
          const snapshot = request.current
          if (!text || !snapshot) { setError('未识别到原文，请试听检查选段后重试。'); return }
          if (sameClip(snapshot, latest.current) && snapshot.transcript === latest.current.transcript) {
            latest.current.onResult(text); setNote('已填入选段原文，请试听核对。')
          } else {
            setResult({ text, snapshot }); setNote('识别期间选段、语言或原文已修改，结果未自动覆盖。')
          }
          return
        }
        if (terminal(response.status)) { setError(String(response.status.error?.message || response.status.message || '识别已取消或未完成。')); return }
      } catch (cause) {
        if (stopped) return
        setError(cause instanceof Error ? cause.message : String(cause))
        if (++failures >= 3) { setDisconnected(true); return }
      }
      timer = setTimeout(() => void poll(), 1500)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [task?.task_id, retry])
  const running = !!task && !terminal(task)
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const elapsed = task ? Math.max(0, Math.floor(((task.finished_at ? Date.parse(task.finished_at) : now) - Date.parse(task.started_at || task.created_at)) / 1000)) : 0
  const stateLabels: Record<string, string> = { pending: '等待识别', running: '正在识别', completed: '选段识别完成', failed: '识别失败', cancelled: '已取消', skipped: '已跳过' }
  async function start() {
    if (submitting || running || !props.valid) return
    request.current = { ...props }
    setSubmitting(true); setError(''); setNote(''); setResult(null)
    try {
      const value = await speechApi.transcribeTask(props.path, props.start, props.end, props.language)
      if (mounted.current) setTask(value)
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (mounted.current) setSubmitting(false) }
  }
  return <div className="reference-clip-asr">
    <div className="row"><button disabled={!props.valid || submitting || running} onClick={() => void start()}>{submitting ? '正在提交…' : running ? '正在识别选段…' : '识别选段原文'}</button><span className="muted">仅识别框选的 {Math.max(0, props.end - props.start).toFixed(1)} 秒，不读取字幕。</span></div>
    {task && <div className="reference-analysis-status" role="status"><div className="row spread"><span>{terminal(task) ? stateLabels[task.state] : task.message || stateLabels[task.state]}</span>{running && <button onClick={() => void tasksApi.cancel(task.task_id).then(setTask).catch(cause => setError(String(cause)))}>取消识别</button>}</div><progress max={1} value={task.progress} aria-label="选段识别进度" /><p className="muted">阶段进度 {Math.round(task.progress * 100)}% · 已用时 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒</p>{running && <p className="muted">模型首次加载可能较慢；此处显示阶段进度，可继续试听。切换录音后可在任务中心查看任务。</p>}</div>}
    {error && <p className="notice error" role="alert">{error}</p>}
    {disconnected && <div className="row"><button onClick={() => setRetry(value => value + 1)}>重新获取识别进度</button><button onClick={() => { setTask(null); setDisconnected(false); setNote('已结束跟踪，原任务可能仍在运行，可在任务中心查看。') }}>结束跟踪</button></div>}
    {note && <p className="muted" role="status">{note}</p>}
    {result && <div className="notice"><p>{result.text}</p><button disabled={!sameClip(result.snapshot, props)} onClick={() => { props.onResult(result.text); setResult(null); setNote('已填入原文，请试听核对。') }}>使用识别结果</button>{!sameClip(result.snapshot, props) && <p>返回识别时的选段和语言后可填入，或重新识别当前选段。</p>}</div>}
  </div>
}
