import { useEffect, useState } from 'react'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { confirmAction } from '@/utils/confirmAction'

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
      if (!await confirmAction(`下次启动使用：${choice.path}\n${capacity(choice.free_bytes)}\n\n${choice.existing ? '将使用此工作目录中已有的配置、任务和音色。' : '新目录将使用全新配置，不复制现有密钥、任务或音色。'}\n旧目录保留，不自动搬移或删除文件。当前自定义路径只属于当前工作目录。确认切换？`)) return
      setWorkspace(await invoke<Workspace>('workspace_schedule_switch', { path: choice.path }))
      setMessage('已保存下次启动的位置。当前仍使用原工作目录；重启后生效。')
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
  return <section className="settings-path-group" aria-label="工作目录">
    <h3>工作目录</h3>
    <p>运行环境、模型、下载缓存和临时文件默认随此目录保存。配置、任务历史和音色也属于所选工作目录。</p>
    {workspace && <>
      <label className="settings-path-label">当前正在使用</label>
      <p style={{ overflowWrap: 'anywhere' }} data-testid="active-workspace">{workspace.active}</p>
      <p>{capacity(workspace.free_bytes)}</p>
      {workspace.pending && <p role="status" style={{ overflowWrap: 'anywhere' }} data-testid="pending-workspace">重启后使用：{workspace.pending}。当前尚未切换。</p>}
      {workspace.fixed_by_environment ? <p>工作目录由启动环境固定，需调整启动环境后重启。</p> : <div style={{ display: 'flex', gap: 12 }}>
        <button className="settings-button" disabled={busy || disabled} onClick={() => void choose()}>选择下次启动的工作目录</button>
        {workspace.pending && <button className="settings-button primary" disabled={busy || disabled} onClick={() => void restart()}>重启并切换</button>}
      </div>}
    </>}
    <p>下方显式自定义路径只作用于当前工作目录。切换到空目录会使用新目录的默认位置；不会搬移旧文件或复制凭据。</p>
    {message && <p role="status">{message}</p>}
  </section>
}
