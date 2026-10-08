import { useId, useState } from 'react'
import { api } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'

type Preview = { token: string; path: string | null; bytes: number; files: { path: string }[]; blockers: string[] }

export default function ModelWeightRemoval({ modelId, onChanged }: { modelId: string; onChanged: () => Promise<void> }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const panelId = useId()
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
  const blocked = !!preview?.blockers.length
  // A rejected ownership check returns no inventory; zero candidates is not a model size.
  const noInventory = blocked && !preview?.path && !preview?.files.length
  return <>
    <button className="model-removal-trigger" disabled={busy} aria-expanded={!!preview} aria-controls={preview ? panelId : undefined}
      onClick={() => preview ? setPreview(null) : void inspect()}>
      {busy ? '检查中…' : preview ? '收起删除预览' : '删除权重…'}
    </button>
    {error && <p className="model-removal-error" role="alert">{error}</p>}
    {preview && <section className="model-removal-panel" id={panelId} aria-label={`${modelId} 删除预览`}>
      <div className="model-removal-heading">
        <strong>删除权重</strong>
        <span className={blocked ? 'model-removal-blocked' : 'model-removal-count'}>
          {blocked ? '暂不可删除' : `${preview.files.length} 个文件 · ${(preview.bytes / 1024 ** 3).toFixed(2)} GB`}
        </span>
      </div>
      <p className="model-removal-target">{modelId}</p>
      {preview.path && <details className="model-path">
        <summary title={preview.path}>目录：{preview.path}</summary>
        <p>{preview.path}</p>
      </details>}
      <p className="model-removal-impact">仅删除应用管理权重，保留运行环境。删除不可恢复。</p>
      {noInventory && <p className="model-removal-empty">安全检查未通过，未生成可删除清单。</p>}
      {blocked && <div className="model-removal-reasons">
        <p>{preview.blockers[0]}</p>
        {preview.blockers.length > 1 && <details>
          <summary>其余 {preview.blockers.length - 1} 项保护原因</summary>
          <ul>{preview.blockers.slice(1).map(reason => <li key={reason}>{reason}</li>)}</ul>
        </details>}
      </div>}
      {preview.files.length > 0 && <details className="model-removal-files">
        <summary>查看 {preview.files.length} 个文件{blocked ? ` · ${(preview.bytes / 1024 ** 3).toFixed(2)} GB` : ''}</summary>
        <ul>{preview.files.map(file => <li key={file.path}>{file.path}</li>)}</ul>
      </details>}
      <div className="model-removal-footer">
        {preview.blockers.some(reason => reason.includes('内存')) && <button disabled={busy} onClick={async () => {
          setBusy(true)
          try { await api.post(base + '/unload'); await inspect() } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
        }}>卸载内存后重新检查</button>}
        <button disabled={busy} onClick={() => setPreview(null)}>取消</button>
        <button className="model-removal-confirm" disabled={busy || blocked} onClick={() => void remove()}>确认删除权重</button>
      </div>
    </section>}
  </>
}
