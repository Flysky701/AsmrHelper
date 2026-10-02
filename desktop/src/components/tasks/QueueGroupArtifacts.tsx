import { useEffect, useState } from 'react'
import { apiUrl } from '@/api/client'
import { tasksApi } from '@/api/tasks'
import type { ArtifactResponse } from '@/api/types'

/** Results are selected by the current attempt's task ID, never by a file stem or a global latest task. */
export default function QueueGroupArtifacts({ taskId }: { taskId: string | null }) {
  const [artifacts, setArtifacts] = useState<ArtifactResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [subtitle, setSubtitle] = useState<{ artifactId: string; text: string } | null>(null)
  const [subtitleId, setSubtitleId] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    setArtifacts([]); setSubtitleId(null); setSubtitle(null); setError('')
    if (!taskId) return
    setLoading(true)
    void tasksApi.artifacts(taskId).then(result => {
      if (!active) return
      if (result.task_id !== taskId || result.artifacts.some(artifact => artifact.task_id !== taskId)) throw new Error('产物任务标识不匹配，未显示结果')
      setArtifacts(result.artifacts)
    }).catch(reason => { if (active) setError(`读取本组产物失败：${String(reason)}`) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [taskId, revision])
  useEffect(() => {
    const controller = new AbortController()
    setSubtitle(null)
    if (!subtitleId || !artifacts.some(artifact => artifact.artifact_id === subtitleId && artifact.task_id === taskId)) return
    void fetch(apiUrl(`/artifacts/${encodeURIComponent(subtitleId)}/file`), { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const content = await response.text()
      if (!controller.signal.aborted) setSubtitle({ artifactId: subtitleId, text: content.length > 512_000 ? `${content.slice(0, 512_000)}\n…预览仅显示前 512 KB` : content })
    }).catch(reason => { if (!controller.signal.aborted) setError(`字幕预览失败：${String(reason)}`) })
    return () => controller.abort()
  }, [subtitleId, taskId, artifacts])
  return <div className="queue-artifacts" aria-label="本组任务产物">
    {!taskId ? <p>本组还没有任务编号，暂无可验证的产物。</p> : <>
      <div className="queue-artifact-heading"><span>本次任务 · {taskId}</span><button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新产物</button></div>
      {loading ? <p role="status">正在读取本组产物…</p> : null}
      {error ? <p className="queue-error" role="alert">{error}</p> : null}
      {!loading && !error && !artifacts.length ? <p>后端尚未返回本组产物。</p> : null}
      {artifacts.map(artifact => <div className="queue-artifact" key={artifact.artifact_id}>
        <div className="queue-artifact-name"><strong>{artifact.label || artifact.type}</strong><small title={artifact.path}>{artifact.path}</small></div>
        {artifact.preview && artifact.type.startsWith('audio.') ? <audio key={`${taskId}:${artifact.artifact_id}`} controls preload="none" src={apiUrl(`/artifacts/${encodeURIComponent(artifact.artifact_id)}/file`)} onError={() => setError('本组音频暂时无法播放，请检查产物是否仍可读取。')} /> : null}
        {/subtitle/i.test(artifact.type) || /\.(vtt|srt|lrc)$/i.test(artifact.path) ? <button type="button" onClick={() => setSubtitleId(value => value === artifact.artifact_id ? null : artifact.artifact_id)}>{subtitleId === artifact.artifact_id ? '收起字幕' : '查看字幕'}</button> : null}
        <button type="button" onClick={() => void navigator.clipboard.writeText(artifact.path).catch(reason => setError(`复制路径失败：${String(reason)}`))}>复制路径</button>
        {subtitleId === artifact.artifact_id ? <pre className="queue-subtitle-preview">{subtitle?.artifactId === artifact.artifact_id ? subtitle.text : '正在读取字幕…'}</pre> : null}
      </div>)}
    </>}
  </div>
}
