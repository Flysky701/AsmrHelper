import { useEffect, useRef, useState } from 'react'

import { tasksApi } from '@/api/tasks'
import type { TaskRecoveryResponse } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'

export default function TaskRecoveryAction({ taskId, onResumed }: {
  taskId: string
  onResumed: (response: TaskStatusResponse) => void
}) {
  const [recovery, setRecovery] = useState<TaskRecoveryResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let cancelled = false
    setRecovery(null)
    setError('')
    tasksApi.recovery(taskId).then((result) => {
      if (!cancelled) setRecovery(result)
    }).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
    })
    return () => { cancelled = true }
  }, [taskId, refresh])

  const resume = async () => {
    if (submitting.current || !recovery?.can_resume) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      const result = await tasksApi.resume(taskId)
      onResumed(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <div style={{ marginTop: 16, padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--panel-muted)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button type="button" disabled={!recovery?.can_resume || busy} onClick={() => void resume()}
          style={{ padding: '8px 14px', borderRadius: 'var(--radius-button)', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--fg)', cursor: !recovery?.can_resume || busy ? 'not-allowed' : 'pointer', opacity: !recovery?.can_resume || busy ? 0.5 : 1 }}>
          {busy ? '正在继续…' : '继续任务'}
        </button>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          {recovery?.can_resume
            ? '复用校验通过的已完成阶段，中断阶段重新执行。'
            : recovery?.reason || (error ? '无法读取恢复信息' : '正在检查恢复信息…')}
        </span>
      </div>
      {error ? <div role="alert" style={{ marginTop: 8, fontSize: 12, color: 'var(--error)' }}>
        {error}
        {!recovery ? <button type="button" onClick={() => setRefresh((value) => value + 1)} style={{ marginLeft: 8 }}>重新检查</button> : null}
      </div> : null}
    </div>
  )
}
