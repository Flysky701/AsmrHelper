import { useEffect, useState } from 'react'
import { speechApi } from '@/api/speech'
import type { HostedVoicePage } from '@/api/speech'
import './FishVoicePicker.css'

export default function FishVoicePicker({ connectionId, value, onSelect }: {
  connectionId: string
  value: string
  onSelect: (id: string) => void
}) {
  const [title, setTitle] = useState('')
  const [workspaceOnly, setWorkspaceOnly] = useState(true)
  const [page, setPage] = useState(1)
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<{ key: string; data?: HostedVoicePage; error?: string }>()
  const requestKey = JSON.stringify([connectionId, title.trim(), workspaceOnly, page, reload])
  const current = result?.key === requestKey ? result : undefined
  const loading = !!connectionId && !current

  useEffect(() => {
    if (!connectionId) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      speechApi.hostedVoices(connectionId, title.trim(), page, workspaceOnly).then(data => {
        if (!cancelled) setResult({ key: requestKey, data })
      }).catch((error: unknown) => {
        if (!cancelled) setResult({ key: requestKey, error: error instanceof Error ? error.message : '获取声音列表失败' })
      })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [connectionId, title, workspaceOnly, page, requestKey])

  return <div className="fish-voice-picker" aria-label="Fish Audio 声音查询">
    <p className="workbench-speech-muted">可使用 Fish 平台已有的克隆声音 ID。此处仅查询和选择声音，不会上传本地参考录音或创建云端克隆。</p>
    <div className="fish-voice-search">
      <label className="workbench-speech-field"><span>查找声音名称</span>
        <input value={title} maxLength={200} placeholder="输入名称筛选候选声音" disabled={!connectionId}
          onChange={event => { setTitle(event.target.value); setPage(1) }} />
      </label>
      <label className="workbench-speech-field"><span>声音范围</span>
        <select value={workspaceOnly ? 'workspace' : 'public'} disabled={!connectionId}
          onChange={event => { setWorkspaceOnly(event.target.value === 'workspace'); setPage(1) }}>
          <option value="workspace">当前工作区</option><option value="public">公开声音</option>
        </select>
      </label>
      <button type="button" disabled={!connectionId || loading} onClick={() => setReload(reload + 1)}>刷新列表</button>
    </div>
    {!connectionId ? <p className="workbench-speech-muted">选择服务连接后可获取声音列表，也可继续手填 ID。</p>
      : loading ? <p role="status" className="workbench-speech-muted">正在获取声音列表…</p>
      : current?.error ? <p role="alert" className="workbench-speech-error">{current.error}。可继续手填 Voice ID，已填内容保持不变。</p>
      : current?.data && <>
        {current.data.items.length ? <label className="workbench-speech-field"><span>可用声音</span>
          <select value={current.data.items.some(item => item.id === value) ? value : ''}
            onChange={event => {
              const selected = current.data?.items.find(item => item.id === event.target.value)
              if (selected && result?.key === requestKey) onSelect(selected.id)
            }}>
            <option value="">选择声音后填入 ID</option>
            {current.data.items.map(item => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}
          </select>
        </label> : <p role="status" className="workbench-speech-muted">没有匹配的声音。可调整名称或声音范围，也可继续手填 ID。</p>}
        <div className="fish-voice-pagination">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button>
          <span>第 {page} 页</span>
          <button type="button" disabled={!current.data.has_more} onClick={() => setPage(page + 1)}>下一页</button>
          <span className="workbench-speech-muted">选择后回填 ID，可继续手动修改。</span>
        </div>
        {current.data.notice && <p className="workbench-speech-muted">{current.data.notice}</p>}
      </>}
  </div>
}
