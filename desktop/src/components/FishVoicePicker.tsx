import { t, useI18n, format } from '@/i18n'
import { useEffect, useState } from 'react'
import { speechApi } from '@/api/speech'
import type { FishVoiceScope, HostedVoicePage } from '@/api/speech'
import './FishVoicePicker.css'

interface Props {
  connectionId: string
  value: string
  onSelect: (id: string, name?: string) => void
}

// Reset filters and pagination when the connection changes; the parent owns the ID.
export default function FishVoicePicker(props: Props) {
  useI18n()
  return <ConnectionVoicePicker key={props.connectionId} {...props} />
}

export function ConnectionVoicePicker({ connectionId, value, onSelect }: Props) {
  useI18n()
  const [title, setTitle] = useState('')
  const [scope, setScope] = useState<FishVoiceScope>('mine_public')
  const [page, setPage] = useState(1)
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<{ key: string; data?: HostedVoicePage; error?: string }>()
  const requestKey = JSON.stringify([connectionId, title.trim(), scope, page, reload])
  const current = result?.key === requestKey ? result : undefined
  const loading = !!connectionId && !current

  useEffect(() => {
    if (!connectionId) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      speechApi.hostedVoices(connectionId, title.trim(), page, scope).then(data => {
        if (!cancelled) setResult({ key: requestKey, data })
      }).catch((error: unknown) => {
        if (!cancelled) setResult({ key: requestKey, error: error instanceof Error ? error.message : '获取声音列表失败' })
      })
    }, 250)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [connectionId, title, scope, page, requestKey])

  return <div className="fish-voice-picker" aria-label={t("Fish Audio 声音查询")}>
    <label className="workbench-speech-field"><span>{t("当前使用的 Voice ID")}</span>
      <input value={value} placeholder={t("选择下方音色，或直接填写 Voice ID")} onChange={event => onSelect(event.target.value)} />
    </label>
    <div className="fish-voice-search">
      <label className="workbench-speech-field"><span>{t("查找声音名称")}</span>
        <input value={title} maxLength={200} placeholder={t("输入名称筛选候选声音")} disabled={!connectionId}
          onChange={event => { setTitle(event.target.value); setPage(1) }} />
      </label>
      <label className="workbench-speech-field"><span>{t("声音范围")}</span>
        <select value={scope} disabled={!connectionId}
          onChange={event => { setScope(event.target.value as FishVoiceScope); setPage(1) }}>
          <option value="mine_public">{t("我的公开音色（API 账号）")}</option>
          <option value="workspace">{t("当前工作区音色")}</option><option value="public">{t("公共音色库（所有作者）")}</option>
        </select>
      </label>
      <button type="button" disabled={!connectionId || loading} onClick={() => setReload(reload + 1)}>{t("刷新列表")}</button>
    </div>
    <details className="workbench-speech-muted"><summary>{t("声音范围说明")}</summary><p>{scope === 'mine_public'
      ? t('仅显示所选连接账号发布的公开音色；无法核实账号时不显示公共库。')
      : scope === 'workspace' ? t('含团队音色，不等同于本人公开库。')
        : t('所有作者的公共音色，不代表属于当前账号。')}</p></details>
    {!connectionId ? <p className="workbench-speech-muted">{t("选择连接以查询音色，或直接填写 ID。")}</p>
      : loading ? <p role="status" className="workbench-speech-muted">{t("正在获取声音列表…")}</p>
      : current?.error ? <p role="alert" className="workbench-speech-error">{t(current.error)}{t("。可手填 Voice ID。")}</p>
      : current?.data && <>
        {current.data.items.length ? <label className="workbench-speech-field"><span>{t("可用声音")}</span>
          <select value={current.data.items.some(item => item.id === value) ? value : ''}
            onChange={event => {
              const selected = current.data?.items.find(item => item.id === event.target.value)
              if (selected && result?.key === requestKey) onSelect(selected.id, selected.name)
            }}>
            <option value="">{value ? t('当前 ID 不在本页时可继续直接使用') : t('选择声音后填入上方 ID')}</option>
            {current.data.items.map(item => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}
          </select>
        </label> : <p role="status" className="workbench-speech-muted">{t("此范围没有匹配的声音。可调整名称或范围，也可继续手填 ID。")}</p>}
        <div className="fish-voice-pagination">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("上一页")}</button>
          <span>{format("第 {0} 页", [page])}</span>
          <button type="button" disabled={!current.data.has_more} onClick={() => setPage(page + 1)}>{t("下一页")}</button>
        </div>
        {current.data.notice && <p className="workbench-speech-muted">{current.data.notice}</p>}
      </>}
  </div>
}
