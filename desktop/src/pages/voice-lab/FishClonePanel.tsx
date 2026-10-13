import { t, useI18n, format } from '@/i18n'
import { useEffect, useRef, useState } from 'react'
import { fishClonesApi } from '@/api/fishClones'
import type { FishClone, FishCloneDraft } from '@/api/fishClones'
import { FishCloneSubmission } from '@/domain/fishCloneSubmission'
import { speechApi } from '@/api/speech'
import { confirmAction } from '@/utils/confirmAction'
import type { ReferenceAsset, SpeechConnection, SpeechRecipe } from '@/api/speech'
import './FishClonePanel.css'

const stateNames: Record<string, string> = { created: '已创建，待就绪', training: '处理中', trained: '远程就绪', failed: '失败', unknown: '结果未知' }

export default function FishClonePanel({ active, assets, connections, onSaved }: {
  active: boolean; assets: ReferenceAsset[]; connections: SpeechConnection[]; onSaved: (recipe: SpeechRecipe) => Promise<void>
}) {
  useI18n()
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
  return <section className="panel fish-clone-panel">
    <h2>{t("Fish 远程克隆")}</h2>
    <p className="muted">{t("将片段与原文上传至 Fish，创建私有音色。创建可能收费，Free 仅指合成档位。")}</p>
    {error && <p role="alert" className="error">{t(error)}</p>}{notice && <p role="status">{notice.startsWith('已提交，状态：') ? format('已提交，状态：{0}。', [t(notice.slice(7, -1))]) : t(notice)}</p>}
    <fieldset className="lab-fieldset" disabled={busy}>
      <div className="recipe-fields">
        <label className="field">{t("Fish 服务连接")}<select value={draft.connection_ref} onChange={event => setDraft(previous => ({ ...previous, connection_ref: event.target.value }))}>
          <option value="">{t("选择连接")}</option>{connections.filter(item => item.provider_id === 'fish_audio').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label className="field">{t("上传的参考素材")}<select value={draft.asset_id} onChange={event => setDraft(previous => ({ ...previous, asset_id: event.target.value }))}>
          <option value="">{t("选择已保存的录音")}</option>{assets.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name || item.id}{!item.confirmed || !item.transcript.trim() ? t('（需核对原文）') : ''}</option>)}
        </select></label>
        <label className="field">{t("远程音色名称")}<input value={draft.title} maxLength={100} onChange={event => setDraft(previous => ({ ...previous, title: event.target.value }))} /></label>
      </div>
      <section className="fish-clone-summary" aria-label={t("远程创建摘要")}>
        <dl>
          <div><dt>{t("上传至")}</dt><dd>{t("Fish Audio · 私有")}{connection && <small>{connection.name}</small>}</dd></div>
          <div><dt>{t("参考片段")}</dt><dd>{asset?.name || (asset ? t('已选片段') : t('尚未选择'))}{asset?.duration != null && <small>{format("{0} 秒 · 已保存的 WAV", [asset.duration.toFixed(1)])}</small>}</dd></div>
          <div><dt>{t("目标音色")}</dt><dd>{draft.title.trim() || t('尚未填写')}</dd></div>
        </dl>
        {asset && <audio aria-label={t("试听所选参考片段")} controls preload="none" src={speechApi.referenceAudio(asset.id)} />}
        <p className="fish-clone-transcript">{asset?.transcript || t('选择素材后显示随片段上传的原文。')}</p>
      </section>
      <div className="fish-clone-submit"><button className="primary" disabled={!connection || !asset?.confirmed || !asset.transcript.trim() || !draft.title.trim() || submitted} onClick={() => void run(async () => {
        const result = await submission.current.submit(draft)
        update(result); setNotice('已提交，状态：' + (stateNames[result.state] || result.state) + '。')
      })}>{busy ? t('处理中…') : submitted ? t('本次已提交') : t('上传片段并创建音色')}</button><span className="muted">{t("只创建音色，不自动试音。")}</span></div>
      <div className="row spread"><h3>{t("创建结果")}</h3><button onClick={() => void run(load)}>{t("刷新记录")}</button></div>
      <p className="muted">{t("结果未知请先到 Fish 核查，勿重复创建。删除本地记录不删除云端音色或录音。")}</p>
      {items.map(item => <div className="item" key={item.id}>
        <strong>{item.title} · {t(stateNames[item.state] || item.state)}{item.legacy_deleted ? t(' · 旧版保留项') : ''}</strong>
        <p className="fish-clone-result-id">Voice ID：{item.remote_voice_id || t('尚未取得')}{item.message && ' · ' + item.message}</p>
        <div className="row">
          {item.remote_voice_id && ['created', 'training'].includes(item.state) && <button onClick={() => void run(async () => update(await fishClonesApi.refresh(item.id)))}>{t("更新状态")}</button>}
          {item.state === 'trained' && <button onClick={() => void run(async () => {
            const recipe = await fishClonesApi.save(item.id); await load(); await onSaved(recipe)
          })}>{item.recipe_id ? t('打开已保存预设') : t('保存到音色库（Free 合成）')}</button>}
          <button disabled={['created', 'training', 'submitting'].includes(item.state)} title={['created', 'training', 'submitting'].includes(item.state) ? t('仍在处理中，请更新状态后再删除') : undefined} onClick={() => void run(async () => {
            if (!await confirmAction(format("删除本地克隆记录“{0}”？不删除任何录音文件、已保存音色或云端音色。无法撤销。", [item.title]))) return
            await fishClonesApi.remove(item.id); setItems(previous => previous.filter(row => row.id !== item.id)); setNotice('已删除本地克隆记录。')
          })}>{t("删除本地记录")}</button>
        </div>
      </div>)}
    </fieldset>
  </section>
}
