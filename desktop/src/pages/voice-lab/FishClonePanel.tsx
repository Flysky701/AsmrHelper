import { useEffect, useRef, useState } from 'react'
import { fishClonesApi } from '@/api/fishClones'
import type { FishClone, FishCloneDraft } from '@/api/fishClones'
import { FishCloneSubmission } from '@/domain/fishCloneSubmission'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, SpeechConnection, SpeechRecipe } from '@/api/speech'
import './FishClonePanel.css'

const stateNames: Record<string, string> = { created: '已创建，待就绪', training: '处理中', trained: '远程就绪', failed: '失败', unknown: '结果未知' }

export default function FishClonePanel({ active, assets, connections, onSaved }: {
  active: boolean; assets: ReferenceAsset[]; connections: SpeechConnection[]; onSaved: (recipe: SpeechRecipe) => Promise<void>
}) {
  const [draft, setDraft] = useState<FishCloneDraft>({ connection_ref: '', asset_id: '', title: '' })
  const [items, setItems] = useState<FishClone[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const submission = useRef(new FishCloneSubmission(fishClonesApi))
  const inFlight = useRef(false)
  const alive = useRef(true)
  const generation = useRef(0)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    if (!active) return
    let current = true
    const version = ++generation.current
    void fishClonesApi.list().then(result => { if (alive.current && current && version === generation.current) setItems(result.items) })
      .catch(cause => { if (alive.current && current && version === generation.current) setError(String(cause)) })
    return () => { current = false }
  }, [active])
  async function run(action: () => Promise<void>) {
    if (inFlight.current) return
    generation.current++
    inFlight.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { if (alive.current) setError(String(cause)) }
    finally { inFlight.current = false; if (alive.current) setBusy(false) }
  }
  async function load() { const result = await fishClonesApi.list(); if (alive.current) setItems(result.items) }
  function update(result: FishClone) { setItems(previous => [...previous.filter(item => item.id !== result.id), result]) }
  const asset = assets.find(item => item.id === draft.asset_id && !item.archived)
  const connection = connections.find(item => item.id === draft.connection_ref && item.provider_id === 'fish_audio')
  const submitted = submission.current.dispatched(draft)
  const lastDeleted = items.filter(item => item.deleted).sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))[0]
  return <section className="panel fish-clone-panel">
    <h2>Fish 远程克隆</h2>
    <p className="muted">将片段与原文上传至 Fish，创建私有音色。创建可能收费，Free 仅指合成档位。</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset className="lab-fieldset" disabled={busy}>
      <div className="recipe-fields">
        <label className="field">Fish 服务连接<select value={draft.connection_ref} onChange={event => setDraft(previous => ({ ...previous, connection_ref: event.target.value }))}>
          <option value="">选择连接</option>{connections.filter(item => item.provider_id === 'fish_audio').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label className="field">上传的参考素材<select value={draft.asset_id} onChange={event => setDraft(previous => ({ ...previous, asset_id: event.target.value }))}>
          <option value="">选择已保存的录音</option>{assets.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name || item.id}{!item.confirmed || !item.transcript.trim() ? '（需核对原文）' : ''}</option>)}
        </select></label>
        <label className="field">远程音色名称<input value={draft.title} maxLength={100} onChange={event => setDraft(previous => ({ ...previous, title: event.target.value }))} /></label>
      </div>
      <section className="fish-clone-summary" aria-label="远程创建摘要">
        <dl>
          <div><dt>上传至</dt><dd>Fish Audio · 私有{connection && <small>{connection.name}</small>}</dd></div>
          <div><dt>参考片段</dt><dd>{asset?.name || (asset ? '已选片段' : '尚未选择')}{asset?.duration != null && <small>{asset.duration.toFixed(1)} 秒 · 已保存的 WAV</small>}</dd></div>
          <div><dt>目标音色</dt><dd>{draft.title.trim() || '尚未填写'}</dd></div>
        </dl>
        {asset && <audio aria-label="试听所选参考片段" controls preload="none" src={speechApi.referenceAudio(asset.id)} />}
        <p className="fish-clone-transcript">{asset?.transcript || '选择素材后显示随片段上传的原文。'}</p>
      </section>
      <div className="fish-clone-submit"><button className="primary" disabled={!connection || !asset?.confirmed || !asset.transcript.trim() || !draft.title.trim() || submitted} onClick={() => void run(async () => {
        const result = await submission.current.submit(draft)
        update(result); setNotice('已提交，状态：' + (stateNames[result.state] || result.state) + '。')
      })}>{busy ? '处理中…' : submitted ? '本次已提交' : '上传片段并创建音色'}</button><span className="muted">只创建音色，不自动试音。</span></div>
      <div className="row spread"><h3>创建结果</h3><button onClick={() => void run(load)}>刷新记录</button></div>
      <p className="muted">结果未知请先到 Fish 核查，勿重复创建。删除仅隐藏本地记录。</p>
      {items.filter(item => !item.deleted).map(item => <div className="item" key={item.id}>
        <strong>{item.title} · {stateNames[item.state] || item.state}</strong>
        <p className="fish-clone-result-id">Voice ID：{item.remote_voice_id || '尚未取得'}{item.message && ' · ' + item.message}</p>
        <div className="row">
          {item.remote_voice_id && ['created', 'training'].includes(item.state) && <button onClick={() => void run(async () => update(await fishClonesApi.refresh(item.id)))}>更新状态</button>}
          {item.state === 'trained' && <button onClick={() => void run(async () => {
            const recipe = await fishClonesApi.save(item.id); await load(); await onSaved(recipe)
          })}>{item.recipe_id ? '打开已保存预设' : '保存到音色库（Free 合成）'}</button>}
          <button disabled={['created', 'training', 'submitting'].includes(item.state)} title={['created', 'training', 'submitting'].includes(item.state) ? '仍在处理中，请更新状态后再删除' : undefined} onClick={() => void run(async () => {
            update(await fishClonesApi.remove(item.id)); setNotice('已删除本地记录，可撤销。')
          })}>删除本地记录</button>
        </div>
      </div>)}
      {lastDeleted && <button onClick={() => void run(async () => {
        update(await fishClonesApi.restore(lastDeleted.id)); setNotice('已恢复本地记录。')
      })}>撤销上次删除</button>}
    </fieldset>
  </section>
}
