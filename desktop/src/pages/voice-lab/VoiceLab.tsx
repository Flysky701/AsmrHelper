import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, SpeechConnection, SpeechLibrary, SpeechPlan, SpeechProvider, SpeechRecipe, SpeechTake, VoiceVariant } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'
import ReferenceLibrary from './ReferenceLibrary'
import { useNavStore } from '@/stores/navStore'
import { useSpeechDraftStore } from '@/stores/speechDraftStore'
import CandidateAudio from './CandidateAudio'
import './VoiceLab.css'

const emptyLibrary: SpeechLibrary = { voices: [], recipes: [], assets: [], experiments: [], takes: [], plans: [], selections: [], assemblies: [], connections: [] }
const variantNames = { hosted: '服务端音色 ID', builtin: '内置说话人 ID', reference: '参考素材', design: '声音描述' }
const modeNames: Record<string, string> = { hosted: '服务端音色', builtin: '内置声音', reference: '参考声音克隆', design: '声音设计' }
const deploymentNames = { local: '本机', lan: '局域网', cloud: '云端' }
const optionNames: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围（top_p）', style_description: '风格描述', tag_density: '标签密度', device: '运算设备', cfg_value: '引导强度', inference_timesteps: '推理步数' }
const blankRecipe = (): SpeechRecipe => ({ id: '', revision: 0, name: '', voice_id: '', provider_id: '', model: '', mode: '', connection_ref: '', variant: { kind: 'reference', value: '', style: 'normal' }, language: 'zh', provider_options: { schema_version: 1 } })
function Field({ title, children }: { title: string; children: ReactNode }) { return <label className="field">{title}{children}</label> }
function json(value: unknown) { return JSON.stringify(value, null, 2) }
function segmentText(plan: SpeechPlan, start: number, end: number) { return Array.from(plan.text).slice(start, end).join('') }

export default function VoiceLab() {
  const [tab, setTab] = useState(0)
  const [library, setLibrary] = useState<SpeechLibrary>(emptyLibrary)
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [showArchivedRules, setShowArchivedRules] = useState(false)
  const [referenceBusy, setReferenceBusy] = useState(false)
  const [ruleList, setRuleList] = useState<SpeechRecipe[]>([])
  const [recipe, setRecipe] = useState<SpeechRecipe>(blankRecipe)
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [connection, setConnection] = useState<Partial<SpeechConnection> & { api_key: string }>({ name: '', provider_id: '', deployment: 'cloud', api_key: '', base_url: '', timeout: 60 })
  const [showConnection, setShowConnection] = useState(false)
  const [probeResult, setProbeResult] = useState<Record<string, unknown> | null>(null)
  const [script, setScript] = useState('')
  const [plan, setPlan] = useState<SpeechPlan | null>(null)
  const [compiled, setCompiled] = useState<Record<string, unknown>[] | null>(null)
  const [experimentId, setExperimentId] = useState('')
  const [tasks, setTasks] = useState<TaskStatusResponse[]>([])
  const [equalLoudness, setEqualLoudness] = useState(false)
  const [comparison, setComparison] = useState<string[]>([])
  const alive = useRef(true)
  const provider = providers.find(item => item.provider_id === recipe.provider_id)
  const connectionProvider = providers.find(item => item.provider_id === connection.provider_id)
  const selectedMode = provider?.modes.find(mode => mode.id === recipe.mode)
  const experiment = library.experiments.find(item => item.id === experimentId)
  const takes = library.takes.filter(item => item.experiment_id === experimentId)
  const legacyRule = !!recipe.id && (!['reference', 'design'].includes(recipe.mode) || !!library.voices.find(item => item.id === recipe.voice_id)?.bindings.length || recipe.variant.style !== 'normal')
  const adoptable = !!recipe.id && !recipeDirty && !recipe.archived

  const refresh = useCallback(async () => {
    const [result, rules] = await Promise.all([speechApi.library(), speechApi.rules(true)])
    if (alive.current) { setLibrary(result); setRuleList(rules.recipes) }
  }, [])
  useEffect(() => {
    alive.current = true
    void Promise.all([speechApi.providers(), speechApi.library(), tasksApi.list(), speechApi.rules(true)]).then(([descriptors, data, taskList, rules]) => {
      if (alive.current) { setProviders(descriptors.providers); setLibrary(data); setRuleList(rules.recipes); setTasks(taskList.tasks.filter(task => task.task_type === 'speech.generate')) }
    }).catch(cause => { if (alive.current) setError('无法加载音色实验室：' + String(cause)) })
    return () => { alive.current = false }
  }, [])
  const pendingIds = tasks.filter(task => task.state === 'pending' || task.state === 'running').map(task => task.task_id).join(',')
  useEffect(() => {
    if (!pendingIds) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const result = await Promise.all(pendingIds.split(',').map(id => tasksApi.get(id)))
        if (!active) return
        setTasks(previous => previous.map(task => result.find(next => next.task_id === task.task_id) || task))
        if (result.some(task => !['pending', 'running'].includes(task.state))) await refresh()
      } catch (cause) { if (active) setError('任务状态更新失败：' + String(cause)) }
      if (active) timer = setTimeout(() => void poll(), 1800)
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [pendingIds, refresh])

  async function run(label: string, operation: () => Promise<void>) {
    if (busy || referenceBusy) return
    setBusy(label); setError(''); setNotice('')
    try { await operation() } catch (cause) { if (alive.current) setError(String(cause)) }
    finally { if (alive.current) setBusy('') }
  }
  function editRecipe(patch: Partial<SpeechRecipe>) { setRecipe(previous => ({ ...previous, ...patch })); setRecipeDirty(true); setCompiled(null) }
  function changeProvider(id: string, variant?: VoiceVariant) {
    setShowConnection(false); setProbeResult(null)
    const descriptor = providers.find(item => item.provider_id === id)
    const mode = descriptor?.modes.find(item => variant && item.variant_kinds.includes(variant.kind)) || descriptor?.modes.find(item => ['reference', 'design'].includes(item.id))
    const options: Record<string, unknown> = { schema_version: 1 }
    Object.entries(descriptor?.options_schema.properties || {}).forEach(([key, field]) => { if (field.default !== undefined) options[key] = field.default })
    editRecipe({ provider_id: id, mode: mode?.id || '', model: mode?.models[0] || '', connection_ref: '',
      variant: variant || { kind: mode?.variant_kinds[0] || 'hosted', value: '', style: 'normal' }, provider_options: options })
  }
  function editConnection() {
    const item = library.connections.find(value => value.id === recipe.connection_ref)
    if (!item) return
    const descriptor = providers.find(value => value.provider_id === item.provider_id)
    setConnection({ id: item.id, name: item.name, provider_id: item.provider_id, deployment: descriptor?.connection_required ? item.deployment : 'local',
      base_url: item.base_url || '', timeout: item.timeout || 60, model_path: item.model_path || '', device: item.device || '', api_key: '' })
    setShowConnection(true)
  }
  async function saveRecipe() {
    if (legacyRule) throw new Error('历史音色保持只读，请新建规则')
    const saved = await speechApi.rule(recipe)
    setRecipe(saved); setRecipeDirty(false); await refresh(); setNotice('已保存音色修订 ' + saved.revision)
  }
  async function generate(segmentId?: string) {
    if (!adoptable || !script.trim()) throw new Error('请选择已保存音色并填写试音台词')
    const currentPlan = plan && plan.text === script ? plan : await speechApi.plan({ text: script })
    setPlan(currentPlan)
    let id = experimentId
    if (!id || library.plans.find(item => item.id === experiment?.plan_id)?.text_hash !== currentPlan.text_hash) {
      const created = await speechApi.experiment((recipe.name || '试音') + ' · ' + new Date().toLocaleString(), currentPlan.id)
      id = created.id; setExperimentId(id); setComparison([])
    }
    const task = await speechApi.generate(id, recipe.id, currentPlan.id, segmentId)
    setTasks(previous => [...previous, task]); await refresh(); setTab(2)
    setNotice('已提交新候选任务，已有结果会保留。')
  }
  function useRecipe(item: SpeechRecipe) { setRecipe(structuredClone(item)); setRecipeDirty(false); setCompiled(null) }
  async function adoptRecipe(take: SpeechTake) {
    const saved = library.recipes.find(item => item.id === take.recipe_id)
    const takePlan = library.plans.find(item => item.id === take.plan_id)
    const intent = takePlan?.segments.find(item => item.id === take.segment_id)
    if (!saved || !intent) throw new Error('此候选的音色规则或试音文本不可用')
    useRecipe(saved); setNotice('已载入此候选使用的音色规则；未采用试音音频')
  }
  function useReference(item: ReferenceAsset) {
    if (recipe.provider_id && recipe.variant.kind === 'reference') editRecipe({ variant: { kind: 'reference', value: item.id, style: 'normal' } })
    else {
      const descriptor = providers.find(p => p.modes.some(mode => mode.id === 'reference'))
      setRecipe({ ...blankRecipe(), name: item.name || '参考音色', provider_id: descriptor?.provider_id || '', mode: 'reference', model: descriptor?.modes.find(mode => mode.id === 'reference')?.models[0] || '', variant: { kind: 'reference', value: item.id, style: 'normal' } }); setRecipeDirty(true)
    }
    setTab(1); setNotice('已选用录音，请选择引擎连接并保存音色。')
  }

  return <div className="speech-lab">
    <header><div className="row spread"><div><h1>声音与音色</h1><p className="muted">录音素材、生成规则与试音记录独立管理。</p></div><button disabled={!!busy || referenceBusy} onClick={() => void run('刷新', refresh)}>刷新</button></div>
      <nav className="tabs" role="tablist" aria-label="声音管理">{['声音库', '我的音色', '试音记录'].map((title, index) => <button key={title} disabled={!!busy || referenceBusy} role="tab" aria-selected={tab === index} onClick={() => (() => { document.querySelectorAll<HTMLAudioElement>('.speech-lab audio').forEach(player => player.pause()); setTab(index) })()}>{title}</button>)}</nav>
    </header>
    <main>{error && <div role="alert" className="notice error">{error}</div>}{notice && <div role="status" className="notice">{notice}</div>}{busy && <p role="status" className="muted">{busy}…</p>}
      <div hidden={tab !== 0}><ReferenceLibrary active={tab === 0} assets={library.assets} refresh={refresh} onUse={useReference} onBusy={setReferenceBusy} /></div>
      <fieldset className="lab-fieldset" disabled={!!busy}>
      {tab === 1 && <div className="columns"><aside className="panel"><div className="row spread"><h2>我的音色</h2><button onClick={() => { setRecipe(blankRecipe()); setRecipeDirty(false); setShowConnection(false); setNotice('') }}>新建音色</button></div><p className="muted">每个音色是一份命名生成规则，保存后即可在工作台调用。试音是可选项。</p>{!ruleList.length && <p className="empty">尚未保存音色。选择参考录音或描述希望生成的声音。</p>}<label><input type="checkbox" checked={showArchivedRules} onChange={event => setShowArchivedRules(event.target.checked)} /> 显示已归档</label>{ruleList.filter(item => showArchivedRules || !item.archived).map(item => <div className={'item ' + (recipe.id === item.id ? 'selected' : '')} key={item.id}><button onClick={() => useRecipe(item)}>{item.archived ? '已归档 · ' : ''}{item.name}</button><p className="muted">{providers.find(p => p.provider_id === item.provider_id)?.name || item.provider_id} · {modeNames[item.mode] || item.mode} · r{item.revision}</p>{item.archived ? <button onClick={() => void run('恢复音色', async () => { await speechApi.restoreRule(item.id); await refresh() })}>恢复</button> : <button onClick={() => void run('归档音色', async () => { await speechApi.archiveRule(item.id); await refresh() })}>归档</button>}</div>)}</aside><div>
        {legacyRule && <div className="notice">这是历史音色，可直接试音或送入工作台，原配置保持只读。{['reference', 'design'].includes(recipe.mode) && <button onClick={() => { setRecipe({ ...blankRecipe(), name: recipe.name + '（副本）', provider_id: recipe.provider_id, model: recipe.model, mode: recipe.mode, connection_ref: recipe.connection_ref, variant: { ...recipe.variant, style: 'normal' }, language: recipe.language, provider_options: { ...recipe.provider_options } }); setRecipeDirty(true); setNotice('已创建独立草稿，不继承旧的发声、情绪或停顿默认值。') }}>复制为新规则</button>}<button disabled={!adoptable} onClick={() => setTab(2)}>试音</button></div>}
        <fieldset className="lab-fieldset" disabled={legacyRule}>
        <section className="panel"><h2>音色生成规则 {recipe.id && <span className="pill">r{recipe.revision}{recipeDirty ? ' · 有未保存修改' : ''}</span>}</h2><div className="grid">
          <Field title="音色名称"><input value={recipe.name} onChange={event => editRecipe({ name: event.target.value })} /></Field>
          <Field title="备注"><input value={recipe.description || ''} onChange={event => editRecipe({ description: event.target.value })} /></Field>
          <Field title="引擎"><select value={recipe.provider_id} onChange={event => changeProvider(event.target.value)}><option value="">选择引擎</option>{providers.filter(item => item.provider_id === recipe.provider_id || item.modes.some(mode => ['reference', 'design'].includes(mode.id))).map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}</select></Field>
          <Field title="生成方式"><select value={recipe.mode} onChange={event => { const mode = provider?.modes.find(item => item.id === event.target.value); editRecipe({ mode: event.target.value, model: mode?.models[0] || '', variant: { kind: mode?.variant_kinds[0] || 'reference', value: '', style: 'normal' } }) }}><option value="">选择方式</option>{provider?.modes.filter(mode => ['reference', 'design'].includes(mode.id) || mode.id === recipe.mode).map(mode => <option key={mode.id} value={mode.id}>{modeNames[mode.id] || mode.id}{!['reference', 'design'].includes(mode.id) ? '（历史配置）' : ''}</option>)}</select></Field>
          <Field title="模型">{selectedMode?.models.length ? <select value={recipe.model} onChange={event => editRecipe({ model: event.target.value })}>{recipe.model && !selectedMode.models.includes(recipe.model) && <option value={recipe.model}>{recipe.model}（已保存）</option>}{selectedMode.models.map(model => <option key={model} value={model}>{model}</option>)}</select> : <input value={recipe.model} placeholder="填写服务文档中的模型 ID" onChange={event => editRecipe({ model: event.target.value })} />}</Field>
          <Field title="连接"><select value={recipe.connection_ref} onChange={event => editRecipe({ connection_ref: event.target.value })}><option value="">选择明确的运行连接</option>{library.connections.filter(item => item.provider_id === recipe.provider_id).map(item => <option key={item.id} value={item.id}>{item.name} · {deploymentNames[item.deployment]}</option>)}</select></Field>
          <Field title={variantNames[recipe.variant.kind]}>{recipe.variant.kind === 'reference' ? <select value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })}><option value="">选择声音库录音</option>{library.assets.map(item => <option key={item.id} value={item.id}>{item.name || item.transcript || item.id}</option>)}</select> : <input value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })} />}</Field>
          {recipe.variant.kind === 'reference' && <div><button onClick={() => setTab(0)}>导入或管理录音</button>{!library.assets.length && <p className="muted">声音库为空，请先导入并保存录音，再选用。</p>}</div>}
          <Field title="语言"><input value={recipe.language} onChange={event => editRecipe({ language: event.target.value })} /></Field>
        </div>
          <div className="grid">{Object.entries(provider?.options_schema.properties || {}).filter(([key]) => key !== 'schema_version').map(([key, field]) => <Field key={key} title={field.title || optionNames[key] || key}>{field.enum ? <select value={String(recipe.provider_options[key] ?? field.default ?? '')} onChange={event => editRecipe({ provider_options: { ...recipe.provider_options, [key]: event.target.value } })}><option value="">默认</option>{field.enum.map(value => <option key={String(value)} value={value}>{value}</option>)}</select> : field.type === 'boolean' ? <input type="checkbox" checked={Boolean(recipe.provider_options[key] ?? field.default)} onChange={event => editRecipe({ provider_options: { ...recipe.provider_options, [key]: event.target.checked } })} /> : <input type={['number', 'integer'].includes(field.type || '') ? 'number' : 'text'} step={field.type === 'integer' ? 1 : 'any'} min={field.minimum} max={field.maximum} title={field.description} value={String(recipe.provider_options[key] ?? field.default ?? '')} onChange={event => { const value = event.target.value; const options = { ...recipe.provider_options }; if (!value) delete options[key]; else options[key] = ['number', 'integer'].includes(field.type || '') ? Number(value) : value; editRecipe({ provider_options: options }) }} />}</Field>)}</div>
          <div className="row">{provider?.connection_required ? <button onClick={() => { if (!recipeDirty || window.confirm('当前音色修改尚未保存，离开并管理外部服务？')) useNavStore.getState().openEngines('external') }}>管理外部语音服务</button> : <><button onClick={() => { setConnection({ name: '', provider_id: recipe.provider_id, deployment: provider?.connection_required ? 'cloud' : 'local', api_key: '', base_url: '', timeout: 60 }); setShowConnection(!showConnection) }}>新建连接</button><button disabled={!recipe.connection_ref || !!busy} onClick={editConnection}>编辑连接</button></>}<button disabled={!recipe.connection_ref || !!busy} onClick={() => void run('检查连接', async () => setProbeResult(await speechApi.probe(recipe.connection_ref, recipe.model, recipe.mode)))}>检查连接</button><button className="primary" disabled={!!busy || !recipe.name.trim() || !recipe.provider_id || !recipe.connection_ref || !recipe.variant.value.trim()} onClick={() => void run('保存配方', saveRecipe)}>保存音色</button><button disabled={!adoptable} onClick={() => setTab(2)}>试音（可选）</button></div>
          {probeResult && <details open><summary>连接检查结果</summary><pre>{json(probeResult)}</pre></details>}{showConnection && !connectionProvider?.connection_required && <div className="item"><h3>{connection.id ? '编辑' : '新建'} {connectionProvider?.name} 连接</h3><div className="grid"><Field title="连接名称"><input value={connection.name || ''} onChange={event => setConnection({ ...connection, name: event.target.value })} /></Field><Field title="运行位置"><select value={connection.deployment} onChange={event => setConnection({ ...connection, deployment: event.target.value as SpeechConnection['deployment'] })}><option value="local">{connectionProvider?.connection_required ? '本机服务' : '本机'}</option>{connectionProvider?.connection_required && <><option value="lan">局域网</option><option value="cloud">云端</option></>}</select></Field>{connectionProvider?.connection_required && <><Field title="API 地址"><input value={connection.base_url || ''} onChange={event => setConnection({ ...connection, base_url: event.target.value })} /></Field><Field title="API 密钥"><input type="password" autoComplete="off" value={connection.api_key} onChange={event => setConnection({ ...connection, api_key: event.target.value })} /></Field><Field title="超时（秒）"><input type="number" min={1} value={connection.timeout || 60} onChange={event => setConnection({ ...connection, timeout: Number(event.target.value) })} /></Field></>}{connectionProvider && !connectionProvider.remote && <><Field title="模型路径（可选）"><input value={connection.model_path || ''} onChange={event => setConnection({ ...connection, model_path: event.target.value })} /></Field><Field title="设备（可选）"><input value={connection.device || ''} onChange={event => setConnection({ ...connection, device: event.target.value })} /></Field></>}</div><button disabled={!!busy || !connection.name?.trim()} onClick={() => void run('保存连接', async () => { const saved = await speechApi.connection(connection); editRecipe({ connection_ref: saved.id }); setConnection({ ...connection, api_key: '' }); setShowConnection(false); await refresh() })}>保存连接</button></div>}
          {provider && <details style={{ marginTop: 14 }}><summary>引擎能力与验证状态</summary><pre>{json(selectedMode?.capabilities || provider.capabilities)}</pre></details>}
        </section>
        </fieldset>
        <section className="panel"><h2>用于正式配音</h2><p className="muted">保存即可使用，无需先试音。</p><button disabled={!adoptable} onClick={() => void run('创建工作台草稿', async () => { const draft = await speechApi.workbenchDraft(recipe.id); useSpeechDraftStore.getState().setRecipe(draft.recipe); useNavStore.getState().setPage('workbench') })}>送入工作台草稿</button></section>
      </div></div>}

      {tab === 2 && <section className="panel"><h2>新试音</h2><Field title="已保存音色"><select value={recipe.id} onChange={event => { const item = library.recipes.find(value => value.id === event.target.value); if (item) useRecipe(item) }}><option value="">选择音色</option>{recipe.id && !ruleList.some(item => item.id === recipe.id) && <option value={recipe.id}>{recipe.name}（历史修订）</option>}{ruleList.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><textarea aria-label="试音原文" rows={4} value={script} onChange={event => { setScript(event.target.value); setCompiled(null) }} placeholder="输入想试听的台词" /><div className="row" style={{ marginTop: 14 }}><button className="primary" disabled={!!busy || !adoptable || !script.trim()} onClick={() => void run('提交试音', () => generate())}>生成试音</button></div><p className="muted">试音按所选连接调用模型，云端服务可能计费。保存音色无需试音。</p><details><summary>高级：检查请求</summary><button disabled={!adoptable || !script.trim()} onClick={() => void run('检查合成请求', async () => { const current = plan?.text === script ? plan : await speechApi.plan({ text: script }); setPlan(current); setCompiled((await speechApi.compile(recipe.id, current.id)).requests) })}>检查引擎请求（不合成）</button>{compiled && <pre>{json(compiled)}</pre>}</details></section>}

      {tab === 2 && <><section className="panel"><div className="row spread"><h2>试音与对比</h2><label><input type="checkbox" checked={equalLoudness} onChange={event => setEqualLoudness(event.target.checked)} /> 校准试听音量</label></div><Field title="试音实验"><select value={experimentId} onChange={event => { setExperimentId(event.target.value); setComparison([]); const exp = library.experiments.find(item => item.id === event.target.value); const saved = library.plans.find(item => item.id === exp?.plan_id); if (saved) { setPlan(saved); setScript(saved.text); setCompiled(null) } }}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><div className="row"><span className="muted">音色：{recipe.name || '未选择'}{recipeDirty ? '（未保存）' : ''}</span><button disabled={!!busy || !adoptable || !plan || script !== plan.text} onClick={() => void run('生成新候选', () => generate())}>再生成一组</button></div>
          {tasks.map(task => <div className="item" key={task.task_id}><div className="row spread"><span>{task.task_id} · {task.state} · {Math.round(task.progress * 100)}%</span>{['pending', 'running'].includes(task.state) && <button onClick={() => void run('取消任务', async () => { const result = await tasksApi.cancel(task.task_id); setTasks(previous => previous.map(item => item.task_id === result.task_id ? result : item)) })}>取消后续生成</button>}</div>{task.message && <p className="muted">{task.message}</p>}{task.error && <p className="error">{json(task.error)}</p>}</div>)}
        </section>
        {!takes.length && <div className="panel empty">尚无已完成的候选。选择音色并输入台词后即可生成试音；失败或未完成的音频不能采用。</div>}
        {plan?.segments.map((segment, index) => <section className="panel" key={segment.id}><div className="row spread"><h3>第 {index + 1} 句 · {segmentText(plan, segment.start, segment.end)}</h3><button disabled={!!busy || !adoptable || script !== plan.text} onClick={() => void run('重生成单句', () => generate(segment.id))}>仅重生成此句</button></div><div className="grid">{takes.filter(take => take.segment_id === segment.id).map(take => <div className="item" key={take.id}><div className="row spread"><strong>{take.id}</strong><label><input type="checkbox" checked={comparison.includes(take.id)} disabled={!comparison.includes(take.id) && (comparison.length >= 2 || comparison.some(id => takes.find(item => item.id === id)?.segment_id !== take.segment_id))} onChange={event => setComparison(event.target.checked ? [...comparison, take.id] : comparison.filter(id => id !== take.id))} /> 对比</label></div><p className="muted">{take.audio?.duration?.toFixed(2) || '—'} 秒 · 生成耗时 {take.elapsed_seconds?.toFixed(1) || '—'} 秒</p><CandidateAudio url={speechApi.takeAudio(take.id)} equalLoudness={equalLoudness} /><div className="row"><button disabled={!!busy} onClick={() => void run('采用候选配方', () => adoptRecipe(take))}>载入此音色</button><button className="primary" disabled={!!busy} onClick={() => void run('采用片段音频', async () => { await speechApi.select({ experiment_id: experimentId, segment_id: take.segment_id, take_id: take.id }); await refresh(); setNotice('已采用该句音频，其余片段保留') })}>{library.selections.some(item => item.experiment_id === experimentId && item.segment_id === segment.id && item.take_id === take.id) ? '已采用音频' : '采用此句音频'}</button></div></div>)}</div></section>)}
        {comparison.length === 2 && <section className="panel"><h2>候选配置差异</h2><div className="grid">{comparison.map(id => { const take = takes.find(item => item.id === id); const other = takes.find(item => item.id === comparison.find(otherId => otherId !== id)); if (!take || !other) return null; const keys = new Set([...Object.keys(take.compiled_request), ...Object.keys(other.compiled_request)]); const diff = Object.fromEntries([...keys].filter(key => json(take.compiled_request[key]) !== json(other.compiled_request[key])).map(key => [key, take.compiled_request[key]])); return <div key={id}><h3>{id}</h3><pre>{Object.keys(diff).length ? json(diff) : '有效配置相同；声音差异可能来自随机生成。'}</pre></div> })}</div></section>}
      </>}

      {tab === 2 && <>
        <section className="panel"><h2>导出本实验采用的音频</h2><p className="muted">逐句采用满意候选后，创建新的组装版本。更换某句候选后需要重新组装。</p><Field title="实验"><select value={experimentId} onChange={event => setExperimentId(event.target.value)}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><button disabled={!!busy || !experimentId} onClick={() => void run('组装已选音频', async () => { await speechApi.assembly(experimentId); await refresh(); setNotice('新的音频组装版本已生成') })}>组装已采用片段</button>{library.assemblies.filter(item => item.experiment_id === experimentId).map(item => <div className="item" key={item.id}><h3>组装版本 {item.revision || item.id}</h3><audio controls src={speechApi.assemblyAudio(item.id)} /><a href={speechApi.assemblyAudio(item.id)} download>下载音频</a></div>)}</section>
      </>}
      </fieldset>
    </main>
  </div>
}
