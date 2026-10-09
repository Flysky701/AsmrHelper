import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'

type Preview = { token: string; blockers: string[]; records: Record<string, number>; files: { path: string; bytes: number }[]; bytes: number }
type LegacyRecord = { id: string; kind: string; item_id: string; directory: string }
const names: Record<string, string> = { experiments: '实验', recipes: '音色', assets: '参考录音', staging: '无引用暂存', 'legacy-trash': '旧版保留数据' }

export async function deleteSpeechData(kind: string, itemId: string, name?: string, extra = ''): Promise<boolean> {
  const base = `/speech/cleanup/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`
  const preview = await api.post<Preview>(base + '/preview')
  if (preview.blockers.length) throw new Error(preview.blockers.join('；'))
  if (!preview.files.length && !Object.keys(preview.records).length) throw new Error('没有可删除的内容')
  const files = preview.files.length
    ? `同时删除 ${preview.files.length} 个应用自有文件（${(preview.bytes / 1024 / 1024).toFixed(2)} MB）。`
    : '仅删除本地记录，不删除音频文件。'
  if (!await confirmAction(`删除“${name || names[kind] || itemId}”？\n${files}保留用户原文件和云端音色。删除无法撤销。${extra}`)) return false
  await api.post(base + '/execute', { token: preview.token, confirmed: true })
  window.dispatchEvent(new Event('speech-cleanup-changed'))
  return true
}

export function SpeechCleanupButton({ kind, itemId, label, name, onChanged, disabled = false }: {
  kind: string; itemId: string; label: string; name?: string; onChanged: () => Promise<void>; disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setError('') }, [kind, itemId])
  return <span className="speech-cleanup">
    <button type="button" disabled={disabled || busy || !itemId} onClick={async () => {
      setBusy(true); setError('')
      try { if (await deleteSpeechData(kind, itemId, name)) await onChanged() }
      catch (cause) { setError(String(cause)) }
      finally { setBusy(false) }
    }}>{label}</button>
    {error && <span role="alert" className="error">{error}</span>}
  </span>
}

export function LegacySpeechData({ onChanged }: { onChanged: () => Promise<void> }) {
  const [items, setItems] = useState<LegacyRecord[]>([])
  const [error, setError] = useState('')
  const reload = () => api.get<LegacyRecord[]>('/speech/cleanup/legacy-records').then(setItems).catch(cause => setError(String(cause)))
  useEffect(() => { void reload(); const listener = () => { void reload() }; window.addEventListener('speech-cleanup-changed', listener); return () => window.removeEventListener('speech-cleanup-changed', listener) }, [])
  if (!items.length && !error) return null
  return <details><summary>旧版保留数据（{items.length}）</summary>
    <p>旧版回收文件仍在原目录，升级不会自动删除。可逐项确认删除；文件可能是唯一副本。</p>
    {error && <p role="alert">{error}</p>}
    {items.map(item => <div key={item.id}>{names[item.kind] || '声音数据'} · {item.item_id}<p>{item.directory}</p>
      <SpeechCleanupButton kind="legacy-trash" itemId={item.id} label="删除此项" name={item.item_id}
        onChanged={async () => { await reload(); await onChanged() }} />
    </div>)}
  </details>
}
