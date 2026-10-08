import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { modelsApi } from '@/api/models'
import type { ModelSummaryResponse } from '@/api/types'
import { nodeInstallModel, nodeModelStatus } from '@/domain/nodeEngineStatus'
import { useNavStore } from '@/stores/navStore'

type Observation = { key: string; label: string; detail: string; positive: boolean; time: string }
export default function GraphEngineControl({ provider, model, category, choices, local, connectionRequired = true, loading = false, unavailable = false,
  connectionSummary, connectionIssue, configurationKey = '', checkConfiguration, configuration, onSelect, onRefresh }: {
  provider: string; model: string | null; category: string; choices: { id: string; name: string }[]; local: boolean
  connectionRequired?: boolean; loading?: boolean; unavailable?: boolean; connectionSummary?: string; connectionIssue?: string; configurationKey?: string
  checkConfiguration?: () => Promise<Record<string, unknown>>; configuration?: ReactNode
  onSelect: (provider: string) => void; onRefresh: () => void
}) {
  const [catalog, setCatalog] = useState<ModelSummaryResponse[]>([])
  const [catalogError, setCatalogError] = useState('')
  const [catalogRevision, setCatalogRevision] = useState(0)
  const [drawer, setDrawer] = useState(false)
  const [checking, setChecking] = useState(false)
  const [observation, setObservation] = useState<Observation | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const request = useRef(0), alive = useRef(true)
  const id = useId(), name = choices.find(item => item.id === provider)?.name || provider || '尚未选择引擎'
  const key = JSON.stringify([provider, model, configurationKey])
  const currentKey = useRef(key); currentKey.current = key
  const installModel = nodeInstallModel(catalog, category, provider, model)
  useEffect(() => {
    let active = true; alive.current = true
    void modelsApi.list().then(result => { if (active) { setCatalog(result); setCatalogError('') } })
      .catch(() => { if (active) setCatalogError('模型目录暂未读取，不能据此判断是否安装。') })
    return () => { active = false; alive.current = false; request.current++ }
  }, [catalogRevision])
  useEffect(() => { request.current++; setChecking(false); setObservation(null) }, [key])
  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (drawer && !element.open) element.showModal()
    if (!drawer && element.open) element.close()
  }, [drawer])
  const observed = observation?.key === key ? observation : null
  const unknownProvider = !loading && !choices.some(item => item.id === provider)
  const status = loading ? '正在读取引擎列表' : unknownProvider && choices.length ? '需要重新选择引擎' : connectionIssue ? '当前节点配置需处理' : unavailable ? '引擎列表未能读取' : checking ? '正在检查' : observed?.label || '尚未检查'
  const statusDetail = unknownProvider && choices.length
    ? `“${name}”不可用。请选择引擎，再点击“确认更换”。`
    : connectionIssue || (unavailable ? '请在“配置与检查”中刷新目录与连接信息。' : observed?.detail || '可在“配置与检查”中检查，不会安装或下载。')
  async function check() {
    if (checking || connectionIssue || unavailable || (!checkConfiguration && (!local || !installModel))) return
    const sequence = ++request.current, snapshotKey = key
    setChecking(true); setObservation(null)
    try {
      let result: Omit<Observation, 'key' | 'time'>
      if (checkConfiguration) {
        const response = await checkConfiguration()
        result = { label: response.ready === true ? '配置完整，运行未验证' : '配置需补充', detail: typeof response.detail === 'string' ? response.detail : '已检查本地配置；未验证远端可达性或合成结果。', positive: false }
      } else result = nodeModelStatus(await modelsApi.status(installModel!.model_id))
      if (alive.current && sequence === request.current && currentKey.current === snapshotKey) setObservation({ ...result, key: snapshotKey, time: new Date().toLocaleTimeString() })
    } catch (cause) {
      if (alive.current && sequence === request.current && currentKey.current === snapshotKey) setObservation({ key: snapshotKey, label: '检查未完成', detail: String(cause instanceof Error ? cause.message : cause), positive: false, time: new Date().toLocaleTimeString() })
    } finally { if (alive.current && sequence === request.current) setChecking(false) }
  }
  const openManagement = (external: boolean) => { useNavStore.getState().openEngines(external ? 'external' : 'local') }
  const assetName = (asset: string) => catalog.find(item => item.model_id === asset)?.display_name || asset
  const refresh = () => { request.current++; setChecking(false); setObservation(null); setCatalog([]); setCatalogError(''); setCatalogRevision(value => value + 1); onRefresh() }
  return <section className="graph-engine-control" aria-label="引擎与运行配置">
    <div className="graph-engine-heading">{choices.length === 1 && choices[0]?.id === provider ? <div><small>引擎</small><strong>{name}</strong></div> : <label htmlFor={id}>引擎<select id={id} value={provider} disabled={loading} onChange={event => onSelect(event.target.value)}>
      {!choices.some(item => item.id === provider) && <option value={provider}>{name}（{loading ? '读取中' : choices.length ? '原引擎不在列表，请重选' : '列表尚未读取'}）</option>}
      {choices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>}
      <button type="button" onClick={() => setDrawer(true)}>{connectionIssue ? '配置当前节点' : '配置与检查'}</button></div>
    <div className={`graph-engine-status${observed?.positive && !connectionIssue ? ' is-positive' : ''}`} role="status"><strong>{status}</strong><p>{statusDetail}</p>{observed && <small>本次检查 {observed.time} · 不代表任务已经运行</small>}</div>
    {connectionSummary && <p className="graph-engine-connection">{connectionSummary}</p>}
    <dialog ref={dialog} className="graph-engine-drawer" aria-labelledby={id + '-title'} onCancel={() => setDrawer(false)} onClose={() => setDrawer(false)} onClick={event => { if (event.target === dialog.current) { const rect = dialog.current.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right) setDrawer(false) } }}>
      <header><h2 id={id + '-title'}>配置与检查 · {name}</h2><button type="button" autoFocus onClick={() => setDrawer(false)}>关闭</button></header>
      <div className="graph-engine-drawer-body"><p>当前模型：{model || '未指定'}</p><p>这里只管理当前引擎的环境与连接，不会改动输入素材、目标语言或已保存音色。</p>
        <section><h3>运行状态</h3><strong>{status}</strong><p>{statusDetail}</p>
          {local && <><p>{installModel ? `资源：${installModel.display_name}` : '尚未唯一匹配模型目录条目，请到模型管理页确认。'}</p>{catalogError && <p role="alert">{catalogError}</p>}</>}
          {installModel && <dl className="graph-engine-install-facts">
            {installModel.runtime_profile && <><dt>托管运行环境</dt><dd>{installModel.runtime_profile}</dd></>}
            <dt>安装能力</dt><dd>{installModel.supports_install ? '可在模型与环境管理中安装' : '目录未提供自动安装；请在管理页查看配置要求'}</dd>
            {installModel.estimated_size_mb != null && <><dt>预计模型大小</dt><dd>{installModel.estimated_size_mb.toLocaleString()} MB</dd></>}
            {!!installModel.required_assets?.length && <><dt>必需资源</dt><dd>{installModel.required_assets.map(assetName).join('、')}</dd></>}
            {!!installModel.recommended_assets?.length && <><dt>建议资源</dt><dd>{installModel.recommended_assets.map(assetName).join('、')}</dd></>}
            {!!installModel.required_system_tools?.length && <><dt>系统工具</dt><dd>{installModel.required_system_tools.join('、')}</dd></>}
          </dl>}
          {!local && !connectionRequired && <p>此引擎无需填写服务地址或密钥。需网络访问；本页尚未验证网络。</p>}
          <button type="button" disabled={checking || !!connectionIssue || unavailable || !checkConfiguration && (!local || !installModel)} onClick={() => void check()}>{checking ? '正在检查…' : checkConfiguration ? '检查当前连接配置' : '检查当前模型环境'}</button>
          <p className="graph-param-note">检查需要一些时间，不会下载模型或生成内容。连接配置检查不代表远端服务已认证或可达。</p>
        </section>
        {configuration && <section><h3>连接与当前节点覆盖</h3>{configuration}</section>}
        <section><h3>{local || !connectionRequired ? '模型与运行环境' : '外部服务'}</h3><p>{local ? '进入现有管理页选择模型、托管环境与安装方式。安装需另行明确操作；管理页会读取环境状态。' : !connectionRequired ? '可在模型与环境管理中查看引擎要求，无需新建服务连接。管理页会读取环境状态；此处不会自动访问网络。' : '进入现有外部服务页配置或编辑服务地址、凭据与默认连接。这里不会自动测试远端服务。'}</p><button type="button" onClick={() => openManagement(!local && connectionRequired)}>{local || !connectionRequired ? '前往模型与运行环境管理' : '前往外部服务设置'}</button>
          {category === 'tts' && local && <button type="button" onClick={() => useNavStore.getState().setPage('voice-lab')}>前往音色页编辑本机连接</button>}
        </section><button type="button" onClick={refresh}>刷新目录与连接信息</button>
      </div>
    </dialog>
  </section>
}
