import { useState } from 'react'
import { api } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'

type Preview = { token: string; path: string | null; bytes: number; files: { path: string }[]; blockers: string[] }

export default function ModelWeightRemoval({ modelId, onChanged }: { modelId: string; onChanged: () => Promise<void> }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const base = '/models/' + encodeURIComponent(modelId)
  async function inspect() {
    setBusy(true); setError('')
    try { setPreview(await api.post<Preview>(base + '/deletion-preview')) }
    catch (cause) { setError(String(cause)) }
    finally { setBusy(false) }
  }
  async function remove() {
    if (!preview || !await confirmAction(`永久删除 ${modelId} 的 ${preview.files.length} 个权重文件（${(preview.bytes / 1024 ** 3).toFixed(2)} GB）？\n目录：${preview.path}\n无法撤销，再次使用需重新下载。`)) return
    setBusy(true); setError('')
    try { await api.delete(base + '?confirmed=true&token=' + encodeURIComponent(preview.token)); setPreview(null); await onChanged() }
    catch (cause) { setError(String(cause)); setPreview(null) }
    finally { setBusy(false) }
  }
  return <div>
    <button disabled={busy} onClick={() => void inspect()}>删除应用管理权重</button>
    {error && <p role="alert">{error}</p>}
    {preview && <div><p>{preview.path || '没有可安全删除的应用目录'} · {preview.files.length} 个文件 · {(preview.bytes / 1024 ** 3).toFixed(2)} GB</p>
      <p>只删除该目录权重；保留运行环境。删除不可恢复。</p>
      {preview.blockers.map(reason => <p key={reason}>{reason}</p>)}
      {preview.blockers.some(reason => reason.includes('内存')) && <button disabled={busy} onClick={async () => {
        setBusy(true)
        try { await api.post(base + '/unload'); await inspect() } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
      }}>卸载内存后重新检查</button>}
      <details><summary>查看文件</summary>{preview.files.map(file => <p key={file.path}>{file.path}</p>)}</details>
      <button disabled={busy || !!preview.blockers.length} onClick={() => void remove()}>确认删除权重</button>
      <button disabled={busy} onClick={() => setPreview(null)}>取消</button>
    </div>}
  </div>
}
