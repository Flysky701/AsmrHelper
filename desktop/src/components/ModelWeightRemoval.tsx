import { t, format as formatMessage, useI18n } from '@/i18n'
import { useId, useState } from 'react'
import { api } from '@/api/client'
import { confirmAction } from '@/utils/confirmAction'

type Preview = { token: string; path: string | null; bytes: number; files: { path: string }[]; blockers: string[] }

export default function ModelWeightRemoval({ modelId, onChanged }: { modelId: string; onChanged: () => Promise<void> }) {
  useI18n()
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
    if (!preview || !await confirmAction(formatMessage("永久删除 {0} 的 {1} 个权重文件（{2} GB）？\n目录：{3}\n无法撤销，再次使用需重新下载。", [modelId, preview.files.length, (preview.bytes / 1024 ** 3).toFixed(2), preview.path ?? '']))) return
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
      {busy ? t("检查中…") : preview ? t("收起删除预览") : t("删除权重…")}
    </button>
    {error && <p className="model-removal-error" role="alert">{t(error)}</p>}
    {preview && <section className="model-removal-panel" id={panelId} aria-label={formatMessage("{0} 删除预览", [modelId])}>
      <div className="model-removal-heading">
        <strong>{t("删除权重")}</strong>
        <span className={blocked ? 'model-removal-blocked' : 'model-removal-count'}>
          {blocked ? t("暂不可删除") : formatMessage("{0} 个文件 · {1} GB", [preview.files.length, (preview.bytes / 1024 ** 3).toFixed(2)])}
        </span>
      </div>
      <p className="model-removal-target">{modelId}</p>
      {preview.path && <details className="model-path">
        <summary title={preview.path}>{t("目录：")}{preview.path}</summary>
        <p>{preview.path}</p>
      </details>}
      <p className="model-removal-impact">{t("仅删除应用管理权重，保留运行环境。删除不可恢复。")}</p>
      {noInventory && <p className="model-removal-empty">{t("未生成删除清单，请先处理下方问题。")}</p>}
      {blocked && <div className="model-removal-reasons">
        <p>{preview.blockers[0]}</p>
        {preview.blockers.length > 1 && <details>
          <summary>{t("其余")}{preview.blockers.length - 1} {t("项保护原因")}</summary>
          <ul>{preview.blockers.slice(1).map(reason => <li key={reason}>{reason}</li>)}</ul>
        </details>}
      </div>}
      {preview.files.length > 0 && <details className="model-removal-files">
        <summary>{t("查看")}{preview.files.length} {t("个文件")}{blocked ? ` · ${(preview.bytes / 1024 ** 3).toFixed(2)} GB` : ''}</summary>
        <ul>{preview.files.map(file => <li key={file.path}>{file.path}</li>)}</ul>
      </details>}
      <div className="model-removal-footer">
        {preview.blockers.some(reason => reason.includes('内存')) && <button disabled={busy} onClick={async () => {
          setBusy(true)
          try { await api.post(base + '/unload'); await inspect() } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
        }}>{t("卸载内存后重新检查")}</button>}
        <button disabled={busy} onClick={() => setPreview(null)}>{t("取消")}</button>
        <button className="model-removal-confirm" disabled={busy || blocked} onClick={() => void remove()}>{t("确认删除权重")}</button>
      </div>
    </section>}
  </>
}
