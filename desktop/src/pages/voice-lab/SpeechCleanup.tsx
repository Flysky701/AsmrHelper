import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'

type Preview = { token: string; blockers: string[]; records: Record<string, number>; files: { path: string; bytes: number }[]; bytes: number; recoverable: boolean }
type Receipt = { id: string; kind: string; item_id: string; created_at: string }
const names: Record<string, string> = { experiments: '实验', recipes: '音色规则', assets: '参考录音', takes: '候选', selections: '采用记录', assemblies: '组装版本', plans: '台词', rule_states: '归档状态', staging: '暂存' }

export function SpeechCleanupButton({ kind, itemId, label, onChanged, disabled = false }: {
  kind: string; itemId: string; label: string; onChanged: () => Promise<void>; disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  useEffect(() => { setPreview(null); setError('') }, [kind, itemId])
  const base = `/speech/cleanup/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`
  async function inspect() {
    setBusy(true); setError('')
    try { setPreview(await api.post<Preview>(base + '/preview')) }
    catch (cause) { setError(String(cause)) }
    finally { setBusy(false) }
  }
  async function execute() {
    if (!preview || !await confirmAction(preview.recoverable
      ? `将本次预览的 ${Object.values(preview.records).reduce((a, b) => a + b, 0)} 条记录和 ${preview.files.length} 个文件移入回收区？可在本页恢复；不会立即释放磁盘空间。`
      : `永久删除回收区中本次预览的 ${preview.files.length} 个文件（${(preview.bytes / 1024 / 1024).toFixed(2)} MB）？此操作无法撤销。`)) return
    setBusy(true); setError('')
    try {
      await api.post(base + '/execute', { token: preview.token, confirmed: true })
      setPreview(null); await onChanged(); window.dispatchEvent(new Event('speech-cleanup-changed'))
    } catch (cause) { setError(String(cause)); setPreview(null) }
    finally { setBusy(false) }
  }
  return <span className="speech-cleanup">
    <button type="button" disabled={disabled || busy || !itemId} onClick={() => void inspect()}>{label}</button>
    {error && <span role="alert" className="error">{error}</span>}
    {preview && <div className="notice"><p>影响：{Object.entries(preview.records).map(([key, count]) => `${names[key] || '记录'}: ${count}`).join('，') || '无记录'}；{preview.files.length} 个文件，{(preview.bytes / 1024 / 1024).toFixed(2)} MB。{preview.recoverable ? '原始用户素材保留，回收区可恢复。' : '永久删除回收区文件，无法撤销。'}</p>
      {preview.blockers.map(reason => <p key={reason}>{reason}</p>)}
      <details><summary>查看文件路径</summary>{preview.files.map(file => <p key={file.path}>{file.path}</p>)}</details>
      <button type="button" disabled={busy || !!preview.blockers.length || (!preview.files.length && !Object.keys(preview.records).length)} onClick={() => void execute()}>{preview.recoverable ? '确认移入回收区' : '确认永久删除'}</button>
      <button type="button" disabled={busy} onClick={() => setPreview(null)}>取消</button>
    </div>}
  </span>
}

export function SpeechCleanupRestore({ onChanged }: { onChanged: () => Promise<void> }) {
  const [receipts, setReceipts] = useState<Receipt[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const reload = () => api.get<Receipt[]>('/speech/cleanup/receipts').then(setReceipts).catch(cause => setError(String(cause)))
  useEffect(() => { void reload(); const listener = () => { void reload() }; window.addEventListener('speech-cleanup-changed', listener); return () => window.removeEventListener('speech-cleanup-changed', listener) }, [])
  return <details><summary>恢复已清理的声音数据（{receipts.length}）</summary>{error && <p role="alert">{error}</p>}{receipts.map(item => <div key={item.id}>{names[item.kind] || '声音数据'} · {item.item_id} · {item.created_at} <button type="button" disabled={busy} onClick={async () => {
    setBusy(true); setError('')
    try { await api.post('/speech/cleanup/restore/' + item.id); await reload(); await onChanged() }
    catch (cause) { setError(String(cause)) }
    finally { setBusy(false) }
  }}>恢复</button><SpeechCleanupButton kind="trash" itemId={item.id} label="永久清除此项" disabled={busy} onChanged={async () => { await reload(); await onChanged() }} /></div>)}</details>
}
