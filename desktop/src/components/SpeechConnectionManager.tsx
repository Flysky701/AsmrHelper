import { useEffect, useRef, useState } from 'react'
import { speechApi } from '@/api/speech'
import type { SpeechConnection, SpeechConnectionDefault, SpeechConnectionDeletionPreview, SpeechProvider } from '@/api/speech'
import { connectionDeploymentNames } from '@/domain/speechConnections'
import './SpeechConnectionManager.css'
import { useConnectionDraftGuard } from '@/hooks/useConnectionDraftGuard'

/** One server catalog, shared by the local voice editor and external services page. */
export default function SpeechConnectionManager({ connections, defaults, providers, providerId, disabled = false, onChanged, protectNavigation = false }: {
  connections: SpeechConnection[]; defaults: SpeechConnectionDefault[]; providers: SpeechProvider[]
  providerId?: string; disabled?: boolean; protectNavigation?: boolean; onChanged: () => Promise<void>
}) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useConnectionDraftGuard({ dirty: false, busy: !!busy, onBlocked: setNotice }, protectNavigation)
  const [preview, setPreview] = useState<SpeechConnectionDeletionPreview | null>(null)
  const [previewFor, setPreviewFor] = useState('')
  const [action, setAction] = useState<'' | 'replace' | 'detach'>('')
  const [replacement, setReplacement] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const generation = useRef(0)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++ } }, [])
  useEffect(() => { generation.current++; setPreview(null); setPreviewFor(''); setBusy(''); setError('') }, [providerId])
  const scope = providerId ? connections.filter(item => item.provider_id === providerId) : connections
  const cancel = () => { generation.current++; setPreview(null); setPreviewFor(''); setAction(''); setReplacement(''); setAcknowledged(false); setBusy('') }
  async function changed() {
    try { await onChanged() } catch { if (alive.current) setError('操作已完成，但目录刷新失败。请刷新后核对；当前草稿不会自动替换。') }
  }
  async function makeDefault(connection: SpeechConnection) {
    if (busy || disabled || !Number.isInteger(connection.revision)) return
    const token = ++generation.current
    setBusy(`default:${connection.id}`); setError(''); setNotice(''); setPreview(null); setPreviewFor('')
    try {
      await speechApi.setDefaultConnection(connection.id, connection.revision!, defaults.find(item => item.provider_id === connection.provider_id)?.revision ?? 0)
      if (!alive.current || token !== generation.current) return
      setNotice(`已将「${connection.name}」设为默认。`)
      await changed()
    } catch (cause) { if (alive.current && token === generation.current) setError(`默认配置未更新：${String(cause)}。请刷新目录核对后重试。`) }
    finally { if (alive.current && token === generation.current) setBusy('') }
  }
  async function inspect(connection: SpeechConnection) {
    if (busy || disabled) return
    const token = ++generation.current
    setBusy(`preview:${connection.id}`); setPreviewFor(connection.id); setPreview(null); setAction(''); setReplacement(''); setAcknowledged(false); setError(''); setNotice('')
    try {
      const result = await speechApi.previewConnectionDeletion(connection.id)
      if (!alive.current || token !== generation.current) return
      if (result.connection.id !== connection.id || result.connection.provider_id !== connection.provider_id) throw new Error('预览返回的连接不匹配')
      setPreview(result)
    } catch (cause) { if (alive.current && token === generation.current) { setPreviewFor(''); setError(`无法预览删除：${String(cause)}`) } }
    finally { if (alive.current && token === generation.current) setBusy('') }
  }
  const blockers = preview?.presets.filter(item => item.builtin || item.kind === 'recipe' && !!item.recipe_id && preview.historical_recipe_ids.includes(item.recipe_id)) ?? []
  const candidates = preview?.replacements.filter(item => item.provider_id === preview.connection.provider_id && item.id !== preview.connection.id) ?? []
  const currentPreviewConnection = preview && connections.find(item => item.id === preview.connection.id)
  const stale = !!preview && (!currentPreviewConnection || currentPreviewConnection.revision !== preview.connection.revision)
  async function remove() {
    if (!preview || !action || busy || disabled || stale || action === 'detach' && !acknowledged || action === 'replace' && (!candidates.some(item => item.id === replacement) || blockers.length)) return
    const token = ++generation.current, target = preview.connection.id
    setBusy(`delete:${target}`); setError('')
    try {
      const result = await speechApi.executeConnectionDeletion(target, preview.token, action, action === 'replace' ? replacement : undefined)
      if (!alive.current || token !== generation.current) return
      if (result.deleted_connection_id !== target) throw new Error('删除响应的连接不匹配，请刷新核对')
      setPreview(null); setPreviewFor('')
      setNotice('连接已删除；当前草稿若仍引用旧连接，请重新选择。')
      await changed()
    } catch (cause) {
      if (alive.current && token === generation.current) { setPreview(null); setPreviewFor(''); setError(`删除未确认完成：${String(cause)}。请刷新目录并重新预览，不会自动重试。`) }
    } finally { if (alive.current && token === generation.current) setBusy('') }
  }
  return <section className="speech-connection-manager" aria-label="运行配置管理">
    <h4>默认与删除</h4><p>默认连接仅用于未绑定的新草稿。</p>
    {scope.map(item => <div className="connection-manager-row" key={item.id}>
      <div><strong>{item.name}</strong><small>{providers.find(provider => provider.provider_id === item.provider_id)?.name || item.provider_id} · {connectionDeploymentNames[item.deployment]}{defaults.some(value => value.provider_id === item.provider_id && value.connection_ref === item.id) ? ' · 默认' : ''}</small></div>
      <div className="connection-manager-actions"><button type="button" disabled={disabled || !!busy || !Number.isInteger(item.revision) || defaults.some(value => value.provider_id === item.provider_id && value.connection_ref === item.id)} onClick={() => void makeDefault(item)}>设为默认</button>
        <button type="button" disabled={disabled || !!busy} aria-label={`删除连接 ${item.name}`} onClick={() => void inspect(item)}>删除</button></div>
    </div>)}
    {!scope.length && <p>此处没有已保存的运行配置。</p>}
    {previewFor && <section className="connection-delete-preview" aria-label="连接删除预览">
      {preview ? <><h4>删除「{preview.connection.name}」</h4>
        <p>当前与归档音色 {preview.recipes.length} 项；历史音色修订 {preview.historical_recipe_ids.length} 项；工作流引用 {preview.presets.length} 项。</p>
        {!!preview.recipes.length && <ul>{preview.recipes.map(item => <li key={item.id}>{item.name} · r{item.revision} · {item.archived ? '已归档' : '当前'}<small>{item.id}</small></li>)}</ul>}
        {!!preview.historical_recipe_ids.length && <details><summary>历史修订引用</summary><ul>{preview.historical_recipe_ids.map(id => <li key={id}>{id}</li>)}</ul></details>}
        {!!preview.presets.length && <ul>{preview.presets.map(item => <li key={`${item.preset_id}:${item.node_id}:${item.kind}:${item.recipe_id || ''}`}>{item.label} · r{item.revision} · {item.node_id} · {item.builtin ? '内置' : '自定义'} · {item.active ? '当前目录' : '已移除目录'}{item.kind === 'recipe' ? ' · 引用音色' : ' · 节点独立配置'}</li>)}</ul>}
        <p>历史任务快照、已有音频、模型文件和凭据会保留。删除只移除连接记录。</p>
        {stale ? <p role="alert">连接已发生变化，请取消后重新预览。</p> : <>
          <label>处理引用<select aria-label="删除连接时如何处理引用" value={action} disabled={!!busy} onChange={event => { setAction(event.target.value as typeof action); setAcknowledged(false) }}><option value="">请明确选择</option><option value="replace" disabled={!candidates.length || !!blockers.length}>替换为同引擎连接</option><option value="detach">保留缺失引用，之后自行重选</option></select></label>
          {!!blockers.length && <p role="alert">部分内置工作流或固定旧音色修订无法自动迁移。替换前请先编辑或复制这些工作流：{blockers.map(item => `${item.label} / ${item.node_id}`).join('、')}。</p>}
          {action === 'replace' && <><label>替换连接<select aria-label="替换连接" value={replacement} disabled={!!busy} onChange={event => setReplacement(event.target.value)}><option value="">选择同引擎连接</option>{candidates.map(item => <option key={item.id} value={item.id}>{item.name} · {connectionDeploymentNames[item.deployment]}</option>)}</select></label><p>当前音色与可迁移的自定义工作流会生成新修订；旧修订与当前未保存草稿保持不变。</p></>}
          {action === 'detach' && <label className="connection-delete-ack"><input type="checkbox" checked={acknowledged} disabled={!!busy} onChange={event => setAcknowledged(event.target.checked)} />我理解引用会保留为缺失，重新选择连接前不能运行；不会自动改用默认。</label>}
        </>}
        <div className="connection-manager-actions"><button type="button" disabled={!!busy || disabled || stale || !action || action === 'detach' && !acknowledged || action === 'replace' && (!replacement || !!blockers.length)} onClick={() => void remove()}>确认删除连接</button><button type="button" disabled={busy.startsWith('delete:')} onClick={cancel}>取消</button></div>
      </> : <><p role="status">正在读取引用…</p><button type="button" onClick={cancel}>取消预览</button></>}
    </section>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>
}
