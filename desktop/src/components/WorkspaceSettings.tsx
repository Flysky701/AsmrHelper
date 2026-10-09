import { useEffect, useState } from 'react'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { confirmAction } from '@/utils/confirmAction'
import { displayPath } from '@/utils/displayPath'

type Workspace = { active: string; pending: string | null; free_bytes: number | null; fixed_by_environment: boolean }
type Choice = { path: string; free_bytes: number | null; existing: boolean }
const capacity = (bytes: number | null) => bytes === null ? '可用空间无法读取' : `可用空间 ${(bytes / 1073741824).toFixed(1)} GB`

export default function WorkspaceSettings({ disabled, onBusy }: { disabled: boolean; onBusy: (busy: boolean) => void }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (isTauri()) void invoke<Workspace>('workspace_info').then(setWorkspace).catch(error => setMessage(String(error)))
  }, [])
  async function choose() {
    if (busy || disabled) return
    setBusy(true); onBusy(true); setMessage('')
    try {
      const choice = await invoke<Choice | null>('workspace_choose')
      if (!choice) return
      if (!await confirmAction(`下次启动使用：${displayPath(choice.path)}\n${capacity(choice.free_bytes)}\n\n${choice.existing ? '将使用此工作目录中已有的配置、任务和音色。' : '新目录将使用全新配置，不复制现有密钥、任务或音色。'}\n旧目录保留，不自动搬移或删除文件。当前自定义路径只属于当前工作目录。确认切换？`)) return
      setWorkspace(await invoke<Workspace>('workspace_schedule_switch', { path: choice.path }))
      setMessage('切换位置已保存，重启后生效。')
    } catch (error) { setMessage(String(error)) }
    finally { setBusy(false); onBusy(false) }
  }
  async function restart() {
    if (busy || disabled) return
    if (!await confirmAction('关闭并重新启动以切换工作目录？未保存的编辑请先保存。排队或运行中的任务会阻止此次切换。')) return
    setBusy(true); onBusy(true); setMessage('')
    try { await invoke('workspace_restart') }
    catch (error) { setMessage(String(error)); setBusy(false); onBusy(false) }
  }
  if (!isTauri()) return null
  return <section className="settings-workspace-card" aria-labelledby="workspace-heading" aria-busy={busy}>
    <header className="settings-workspace-header">
      <h3 id="workspace-heading">工作目录</h3>
      {workspace && <span className="settings-workspace-capacity">{capacity(workspace.free_bytes)}</span>}
    </header>
    {workspace && <>
      <div className="settings-workspace-current">
        <span className="settings-workspace-label">当前位置</span>
        <p className="settings-workspace-path" data-testid="active-workspace">{displayPath(workspace.active)}</p>
      </div>
      {workspace.pending && <div className="settings-workspace-pending" role="status">
        <span className="settings-workspace-label">下次启动位置</span>
        <p className="settings-workspace-path" data-testid="pending-workspace">{displayPath(workspace.pending)}</p>
      </div>}
    </>}
    <p className="settings-workspace-description">保存配置、任务和音色，也是模型、运行环境与缓存的默认位置。</p>
    {workspace && <>
      {workspace.fixed_by_environment ? <p className="settings-workspace-help">工作目录由启动环境固定，需调整启动环境后重启。</p> : <div className="settings-workspace-actions">
        <button type="button" className="settings-button" disabled={busy || disabled} onClick={() => void choose()}>{busy ? '处理中…' : '更改工作目录'}</button>
        <span className="settings-workspace-help">下次启动生效</span>
        {workspace.pending && <button type="button" className="settings-button primary" disabled={busy || disabled} onClick={() => void restart()}>重启并切换</button>}
      </div>}
    </>}
    <details className="settings-workspace-rules">
      <summary>切换目录会怎样？</summary>
      <p>自定义路径只适用于当前工作目录。切换后使用新目录的配置，旧文件和凭据不会自动迁移。</p>
    </details>
    {message && <p className="settings-workspace-message" role="status">{message}</p>}
  </section>
}
