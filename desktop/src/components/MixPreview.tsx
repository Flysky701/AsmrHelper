import { useEffect, useRef, useState } from 'react'
import { api, apiUrl } from '@/api/client'
import { inputPathKey } from '@/domain/workbenchInput'

interface Source {
  task_id: string
  input_path: string
  label: string
  created_at: string
  uses_vocals: boolean
}

interface Props {
  inputPaths: string[]
  originalVolume: number
  ttsVolumeRatio: number
  ttsDelay: number
}

export default function MixPreview({ inputPaths, originalVolume, ttsVolumeRatio, ttsDelay }: Props) {
  const [sources, setSources] = useState<Source[]>([])
  const [taskId, setTaskId] = useState('')
  const [start, setStart] = useState(0)
  const [loading, setLoading] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [error, setError] = useState('')
  const [audio, setAudio] = useState('')
  const [refresh, setRefresh] = useState(0)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const selectedPaths = inputPaths.map(inputPathKey).sort().join('\n')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    void api.get<{ sources: Source[] }>('/tasks/mix-preview/sources').then(result => {
      if (!active) return
      const paths = new Set(selectedPaths.split('\n').filter(Boolean))
      const matching = result.sources.filter(source => !paths.size || paths.has(inputPathKey(source.input_path)))
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
      setSources(matching)
      setTaskId(previous => matching.some(source => source.task_id === previous) ? previous : matching[0]?.task_id || '')
    }).catch(cause => { if (active) setError(`无法获取试听素材：${String(cause)}`) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [selectedPaths, refresh])

  useEffect(() => {
    generation.current += 1
    controller.current?.abort()
    setRendering(false)
    setAudio('')
    setError('')
  }, [taskId, selectedPaths, originalVolume, ttsVolumeRatio, ttsDelay, start, refresh])

  useEffect(() => () => { if (audio) URL.revokeObjectURL(audio) }, [audio])
  useEffect(() => () => { generation.current += 1; controller.current?.abort() }, [])

  async function preview() {
    const current = ++generation.current
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    setRendering(true)
    setError('')
    setAudio('')
    try {
      const response = await fetch(apiUrl(`/tasks/${encodeURIComponent(taskId)}/mix-preview`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: abort.signal,
        body: JSON.stringify({ original_volume: originalVolume, tts_volume_ratio: ttsVolumeRatio,
          tts_delay: ttsDelay, start_seconds: start }),
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => null)
        throw new Error(detail?.error?.message || detail?.detail || `HTTP ${response.status}`)
      }
      const blob = await response.blob()
      if (generation.current === current) setAudio(URL.createObjectURL(blob))
    } catch (cause) {
      if (generation.current === current && !abort.signal.aborted) setError(`试听失败：${String(cause)}`)
    } finally { if (generation.current === current) setRendering(false) }
  }

  const selected = sources.find(source => source.task_id === taskId)
  return <div className="mix-preview" style={{ marginTop: 18, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <strong style={{ fontSize: 14 }}>混音试听</strong>
      <button type="button" disabled={loading || rendering} onClick={() => setRefresh(value => value + 1)}>{loading ? '查找中…' : '刷新素材'}</button>
    </div>
    <p style={{ fontSize: 12, color: 'var(--muted)' }}>使用已有配音试听当前音量和延迟，最长 15 秒，不重新调用语音合成服务。</p>
    {!loading && !sources.length && !error && <p style={{ fontSize: 12, color: 'var(--muted)' }}>尚无{inputPaths.length ? '所选音频的' : ''}可用配音。请先运行任务至语音合成完成，再刷新素材。</p>}
    {!!sources.length && <div style={{ display: 'flex', alignItems: 'end', gap: 12, flexWrap: 'wrap' }}>
      <label style={{ display: 'grid', gap: 6, fontSize: 12, flex: '1 1 240px', minWidth: 0 }}>已有任务素材
        <select style={{ width: '100%', padding: 8 }} value={taskId} disabled={loading} onChange={event => setTaskId(event.target.value)}>
          {sources.map(source => <option key={source.task_id} value={source.task_id}>{source.label} · {source.task_id}</option>)}
        </select>
      </label>
      <label style={{ display: 'grid', gap: 6, fontSize: 12 }}>起点（秒）
        <input style={{ width: 95, padding: 8 }} type="number" min={0} step={1} value={start} onChange={event => setStart(Math.max(0, Number(event.target.value) || 0))} />
      </label>
      <button type="button" disabled={!taskId || loading || rendering} onClick={() => void preview()}>{rendering ? '生成试听中…' : '生成试听'}</button>
    </div>}
    {selected?.uses_vocals && <p style={{ fontSize: 12, color: 'var(--muted)' }}>该任务使用分离后的人声轨混音，试听保持相同素材。</p>}
    {error && <p role="alert" style={{ color: 'var(--danger)', fontSize: 12 }}>{error}</p>}
    {audio && <audio controls src={audio} style={{ marginTop: 12, width: '100%' }} />}
    <style>{`
      .mix-preview button { padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--fg); font: inherit; font-size: 13px; cursor: pointer; }
      .mix-preview button:disabled { opacity: .55; cursor: default; }
      .mix-preview input, .mix-preview select { border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--fg); font: inherit; }
    `}</style>
  </div>
}
