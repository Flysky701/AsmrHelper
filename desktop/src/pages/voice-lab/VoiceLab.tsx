import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { Delivery, ReferenceAsset, SpeechConnection, SpeechLibrary, SpeechPlan, SpeechProvider, SpeechRecipe, SpeechTake, SpeechVoice, VoiceVariant, Waveform } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'
import { FILE_FILTERS, useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import { useSpeechDraftStore } from '@/stores/speechDraftStore'
import CandidateAudio from './CandidateAudio'
import './VoiceLab.css'

const emptyLibrary: SpeechLibrary = { voices: [], recipes: [], assets: [], experiments: [], takes: [], plans: [], selections: [], assemblies: [], connections: [] }
const styles: { value: Delivery; label: string }[] = [{ value: 'normal', label: '普通' }, { value: 'soft', label: '轻声' }, { value: 'whisper', label: '耳语' }]
const variantNames = { hosted: '服务端音色 ID', builtin: '内置说话人 ID', reference: '参考素材', design: '声音描述' }
const modeNames: Record<string, string> = { hosted: '服务端音色', builtin: '内置声音', reference: '参考声音克隆', design: '声音设计' }
const deploymentNames = { local: '本机', lan: '局域网', cloud: '云端' }
const emotionNames: Record<string, string> = { neutral: '自然', happy: '愉快', sad: '悲伤', angry: '生气', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const optionNames: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围（top_p）', style_description: '风格描述', tag_density: '标签密度', device: '运算设备', cfg_value: '引导强度', inference_timesteps: '推理步数' }
const blankVoice = (): SpeechVoice => ({ id: '', name: '', description: '', bindings: [], default_binding: '' })
const blankRecipe = (): SpeechRecipe => ({ id: '', revision: 0, name: '', voice_id: '', provider_id: '', model: '', mode: '', connection_ref: '', variant: { kind: 'hosted', value: '', style: 'normal' }, language: 'zh', provider_options: { schema_version: 1 } })
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
  const [voice, setVoice] = useState<SpeechVoice>(blankVoice)
  const [recipe, setRecipe] = useState<SpeechRecipe>(blankRecipe)
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [connection, setConnection] = useState<Partial<SpeechConnection> & { api_key: string }>({ name: '', provider_id: '', deployment: 'cloud', api_key: '', base_url: '', timeout: 60 })
  const [showConnection, setShowConnection] = useState(false)
  const [probeResult, setProbeResult] = useState<Record<string, unknown> | null>(null)
  const [script, setScript] = useState('')
  const [plan, setPlan] = useState<SpeechPlan | null>(null)
  const [planDirty, setPlanDirty] = useState(false)
  const [compiled, setCompiled] = useState<Record<string, unknown>[] | null>(null)
  const [experimentId, setExperimentId] = useState('')
  const [tasks, setTasks] = useState<TaskStatusResponse[]>([])
  const [equalLoudness, setEqualLoudness] = useState(false)
  const [comparison, setComparison] = useState<string[]>([])
  const [source, setSource] = useState<(Waveform & { id: string; path: string }) | null>(null)
  const [cropStart, setCropStart] = useState(0)
  const [cropEnd, setCropEnd] = useState(10)
  const [transcript, setTranscript] = useState('')
  const [language, setLanguage] = useState('zh')
  const [confirmed, setConfirmed] = useState(false)
  const [asset, setAsset] = useState<ReferenceAsset | null>(null)
  const [waveform, setWaveform] = useState<Waveform | null>(null)
  const [analyzed, setAnalyzed] = useState<Awaited<ReturnType<typeof speechApi.analyze>> | null>(null)
  const sourcePlayer = useRef<HTMLAudioElement>(null)
  const playingCrop = useRef(false)
  const alive = useRef(true)
  const { selectFiles } = useFileSelector()
  const provider = providers.find(item => item.provider_id === recipe.provider_id)
  const connectionProvider = providers.find(item => item.provider_id === connection.provider_id)
  const selectedMode = provider?.modes.find(mode => mode.id === recipe.mode)
  const experiment = library.experiments.find(item => item.id === experimentId)
  const takes = library.takes.filter(item => item.experiment_id === experimentId)
  const adoptable = !!recipe.id && !recipeDirty

  const refresh = useCallback(async () => {
    const result = await speechApi.library()
    if (alive.current) setLibrary(result)
  }, [])
  useEffect(() => {
    alive.current = true
    void Promise.all([speechApi.providers(), speechApi.library(), tasksApi.list()]).then(([descriptors, data, taskList]) => {
      if (alive.current) { setProviders(descriptors.providers); setLibrary(data); setTasks(taskList.tasks.filter(task => task.task_type === 'speech.generate')) }
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
    setBusy(label); setError(''); setNotice('')
    try { await operation() } catch (cause) { if (alive.current) setError(String(cause)) }
    finally { if (alive.current) setBusy('') }
  }
  function editRecipe(patch: Partial<SpeechRecipe>) { setRecipe(previous => ({ ...previous, ...patch })); setRecipeDirty(true); setCompiled(null) }
  function changeProvider(id: string, variant?: VoiceVariant) {
    setShowConnection(false); setProbeResult(null)
    variant ||= library.voices.find(item => item.id === recipe.voice_id)?.bindings.find(binding => binding.provider_id === id)?.variants[0]
    const descriptor = providers.find(item => item.provider_id === id)
    const mode = descriptor?.modes.find(item => variant && item.variant_kinds.includes(variant.kind)) || descriptor?.modes[0]
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
    const saved = await speechApi.recipe(recipe)
    setRecipe(saved); setRecipeDirty(false); await refresh(); setNotice('已保存配方修订 ' + saved.revision)
  }
  async function generate(segmentId?: string) {
    if (!plan || !recipe.id || recipeDirty || planDirty) throw new Error('请先保存配方与演绎方案')
    let id = experimentId
    if (!id || library.plans.find(item => item.id === experiment?.plan_id)?.text_hash !== plan.text_hash) {
      const created = await speechApi.experiment((recipe.name || '试音') + ' · ' + new Date().toLocaleString(), plan.id)
      id = created.id; setExperimentId(id)
    }
    const task = await speechApi.generate(id, recipe.id, plan.id, segmentId)
    setTasks(previous => [...previous, task]); await refresh(); setTab(2)
    setNotice('已提交新候选任务，已有结果会保留。')
  }
  async function inspectReference() {
    const paths = await selectFiles({ multiple: false, filters: [FILE_FILTERS.audio] })
    if (!paths[0]) return
    const result = await speechApi.inspect(paths[0])
    setSource(result); setCropStart(0); setCropEnd(Math.min(10, result.duration)); setTranscript(''); setConfirmed(false); setAnalyzed(null)
  }
  async function openAsset(item: ReferenceAsset) { setAsset(item); setWaveform(await speechApi.waveform(item.id)) }
  function updateSegment(id: string, patch: Partial<SpeechPlan['segments'][number]>) {
    if (!plan) return
    setPlan({ ...plan, segments: plan.segments.map(segment => segment.id === id ? { ...segment, ...patch } : segment) })
    setPlanDirty(true); setCompiled(null)
  }
  function useRecipe(item: SpeechRecipe) { setRecipe(structuredClone(item)); setRecipeDirty(false); setCompiled(null) }
  async function adoptRecipe(take: SpeechTake) {
    const saved = library.recipes.find(item => item.id === take.recipe_id)
    const takePlan = library.plans.find(item => item.id === take.plan_id)
    const intent = takePlan?.segments.find(item => item.id === take.segment_id)
    if (!saved || !intent) throw new Error('此候选的配方或演绎方案不可用')
    const adopted = await speechApi.recipe({ ...saved, default_delivery: intent.delivery,
      default_emotion: intent.emotion, default_pause_ms: intent.pause_ms })
    useRecipe(adopted); await refresh(); setNotice('已保存候选配置与演绎默认值的新修订；未采用试音音频')
  }
  async function analyzeSource(separate: boolean) {
    if (!source) return
    const result = await speechApi.analyze(source.path, language, separate)
    setAnalyzed(result); setConfirmed(false)
  }
  async function createPlan() {
    const created = await speechApi.plan({ text: script })
    const hasDefaults = (recipe.default_delivery && recipe.default_delivery !== 'normal') || (recipe.default_emotion && recipe.default_emotion !== 'neutral') || recipe.default_pause_ms
    const saved = hasDefaults ? await speechApi.plan({ text: created.text, segments: created.segments.map(segment => ({ ...segment,
      delivery: recipe.default_delivery || 'normal', emotion: recipe.default_emotion || 'neutral', pause_ms: recipe.default_pause_ms || 0 })) }) : created
    setPlan(saved); setPlanDirty(false); setExperimentId(''); setCompiled(null); await refresh()
  }
  const waveformSvg = (data: Waveform, start = 0, end = data.duration) => <svg className="waveform" viewBox="0 0 600 100" preserveAspectRatio="none" role="img" aria-label="真实音频波形">
    <rect x={600 * start / Math.max(data.duration, .001)} width={600 * (end - start) / Math.max(data.duration, .001)} height="100" fill="var(--accent-soft)" />
    {data.peaks.map((peak, index) => <line key={index} x1={index * 600 / data.peaks.length} x2={index * 600 / data.peaks.length} y1={50 - Math.min(1, Math.abs(peak)) * 45} y2={50 + Math.min(1, Math.abs(peak)) * 45} stroke="var(--accent)" strokeWidth="1" />)}
  </svg>

  return <div className="speech-lab">
    <header><div className="row spread"><div><h1>音色实验室</h1><p className="muted">管理声音来源，逐句演绎，保留每次试音。</p></div><button disabled={!!busy} onClick={() => void run('刷新', refresh)}>刷新声音库</button></div>
      <nav className="tabs" role="tablist" aria-label="音色实验室步骤">{['声音与素材', '台词与演绎', '试音与对比', '用于配音'].map((title, index) => <button key={title} role="tab" aria-selected={tab === index} onClick={() => setTab(index)}>{index + 1}　{title}</button>)}</nav>
    </header>
    <main>{error && <div role="alert" className="notice error">{error}</div>}{notice && <div role="status" className="notice">{notice}</div>}{busy && <p role="status" className="muted">{busy}…</p>}
      {tab === 0 && <div className="columns"><aside>
        <section className="panel"><div className="row spread"><h2>声音库</h2><button onClick={() => setVoice(blankVoice())}>新建声音</button></div>
          {!library.voices.length && <p className="empty">尚无声音。创建一个声音，再为普通、轻声或耳语配置实际来源。</p>}
          {library.voices.map(item => <div className={'item ' + (voice.id === item.id ? 'selected' : '')} key={item.id}><button onClick={() => setVoice(structuredClone(item))}>{item.name}</button><p className="muted">{item.bindings.length} 个引擎实现 · {item.description}</p></div>)}
        </section>
        <section className="panel"><h2>已保存配方</h2>{!library.recipes.length && <p className="empty">保存配方后可在新任务中复用。</p>}{library.recipes.map(item => <div className={'item ' + (recipe.id === item.id ? 'selected' : '')} key={item.id}><button onClick={() => useRecipe(item)}>{item.name} · r{item.revision}</button><p className="muted">{item.provider_id} · {item.model}</p></div>)}</section>
      </aside><div>
        <section className="panel"><h2>声音身份</h2><div className="grid"><Field title="声音名称"><input value={voice.name} onChange={event => setVoice({ ...voice, name: event.target.value })} /></Field><Field title="描述"><input value={voice.description} onChange={event => setVoice({ ...voice, description: event.target.value })} /></Field></div>
          {voice.bindings.map((binding, index) => <div className="item" key={index}><div className="row spread"><strong>{providers.find(item => item.provider_id === binding.provider_id)?.name || binding.provider_id}</strong><label><input type="radio" checked={voice.default_binding === binding.provider_id} onChange={() => setVoice({ ...voice, default_binding: binding.provider_id })} /> 默认实现</label><button onClick={() => setVoice({ ...voice, bindings: voice.bindings.filter((_, i) => i !== index), default_binding: voice.default_binding === binding.provider_id ? (voice.bindings.find((_, i) => i !== index)?.provider_id || '') : voice.default_binding })}>移除此实现</button></div>
            {binding.variants.map((variant, vi) => <div className="grid" key={vi} style={{ marginTop: 14 }}><Field title="声音版本"><select value={variant.style} onChange={event => { const next = structuredClone(voice); next.bindings[index]!.variants[vi]!.style = event.target.value as Delivery; setVoice(next) }}>{styles.map(style => <option key={style.value} value={style.value}>{style.label}</option>)}</select></Field><Field title="声音来源"><select value={variant.kind} onChange={event => { const next = structuredClone(voice); next.bindings[index]!.variants[vi] = { ...variant, kind: event.target.value as VoiceVariant['kind'], value: '' }; setVoice(next) }}>{[...new Set(providers.find(item => item.provider_id === binding.provider_id)?.modes.flatMap(mode => mode.variant_kinds) || [])].map(kind => <option key={kind} value={kind}>{variantNames[kind]}</option>)}</select></Field><Field title={variantNames[variant.kind]}>{variant.kind === 'reference' ? <select value={variant.value} onChange={event => { const next = structuredClone(voice); next.bindings[index]!.variants[vi]!.value = event.target.value; setVoice(next) }}><option value="">选择素材</option>{library.assets.map(item => <option key={item.id} value={item.id}>{item.transcript || item.id}</option>)}</select> : <input value={variant.value} onChange={event => { const next = structuredClone(voice); next.bindings[index]!.variants[vi]!.value = event.target.value; setVoice(next) }} />}</Field></div>)}
            <button disabled={binding.variants.length >= 3} onClick={() => { const next = structuredClone(voice); const style = styles.find(item => !binding.variants.some(variant => variant.style === item.value))?.value; if (style) { next.bindings[index]!.variants.push({ kind: binding.variants[0]?.kind || 'hosted', value: '', style }); setVoice(next) } }}>添加声音版本</button>
          </div>)}
          <div className="row" style={{ marginTop: 14 }}><select aria-label="添加引擎实现" value="" onChange={event => { const item = providers.find(p => p.provider_id === event.target.value); if (item) setVoice({ ...voice, default_binding: voice.default_binding || item.provider_id, bindings: [...voice.bindings, { provider_id: item.provider_id, variants: [{ kind: item.modes[0]?.variant_kinds[0] || 'hosted', value: '', style: 'normal' }] }] }) }}><option value="">添加引擎实现…</option>{providers.filter(item => !voice.bindings.some(binding => binding.provider_id === item.provider_id)).map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}</select><button className="primary" disabled={!!busy || !voice.name.trim() || !voice.bindings.length} onClick={() => void run('保存声音', async () => { setVoice(await speechApi.voice(voice)); await refresh(); setNotice('声音已保存') })}>保存声音</button></div>
        </section>
        <section className="panel"><h2>合成配方 {recipe.id && <span className="pill">r{recipe.revision}{recipeDirty ? ' · 有未保存修改' : ''}</span>}</h2><div className="grid">
          <Field title="配方名称"><input value={recipe.name} onChange={event => editRecipe({ name: event.target.value })} /></Field>
          <Field title="声音"><select value={recipe.voice_id} onChange={event => { const item = library.voices.find(v => v.id === event.target.value); if (item) { changeProvider(item.default_binding, item.bindings.find(b => b.provider_id === item.default_binding)?.variants[0]); editRecipe({ voice_id: item.id }) } }}><option value="">选择已保存声音</option>{library.voices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
          <Field title="引擎"><select disabled={!recipe.voice_id} value={recipe.provider_id} onChange={event => changeProvider(event.target.value)}><option value="">选择声音已绑定的引擎</option>{providers.filter(item => library.voices.find(saved => saved.id === recipe.voice_id)?.bindings.some(binding => binding.provider_id === item.provider_id)).map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}</select></Field>
          <Field title="模式"><select value={recipe.mode} onChange={event => { const mode = provider?.modes.find(item => item.id === event.target.value); editRecipe({ mode: event.target.value, model: mode?.models[0] || '', variant: { ...recipe.variant, kind: mode?.variant_kinds[0] || 'hosted', value: '' } }) }}>{provider?.modes.map(mode => <option key={mode.id} value={mode.id}>{modeNames[mode.id] || mode.id}</option>)}</select></Field>
          <Field title="模型">{selectedMode?.models.length ? <select value={recipe.model} onChange={event => editRecipe({ model: event.target.value })}>{recipe.model && !selectedMode.models.includes(recipe.model) && <option value={recipe.model}>{recipe.model}（已保存）</option>}{selectedMode.models.map(model => <option key={model} value={model}>{model}</option>)}</select> : <input value={recipe.model} placeholder="填写服务文档中的模型 ID" onChange={event => editRecipe({ model: event.target.value })} />}</Field>
          <Field title="连接"><select value={recipe.connection_ref} onChange={event => editRecipe({ connection_ref: event.target.value })}><option value="">选择明确的运行连接</option>{library.connections.filter(item => item.provider_id === recipe.provider_id).map(item => <option key={item.id} value={item.id}>{item.name} · {deploymentNames[item.deployment]}</option>)}</select></Field>
          <Field title="声音版本"><select value={recipe.variant.style} onChange={event => { const style = event.target.value as Delivery; const variant = library.voices.find(item => item.id === recipe.voice_id)?.bindings.find(item => item.provider_id === recipe.provider_id)?.variants.find(item => item.style === style); editRecipe({ variant: variant || { ...recipe.variant, style, value: '' } }) }}>{styles.map(style => <option key={style.value} value={style.value}>{style.label}</option>)}</select></Field>
          <Field title={variantNames[recipe.variant.kind]}>{recipe.variant.kind === 'reference' ? <select value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })}><option value="">选择参考素材</option>{library.assets.map(item => <option key={item.id} value={item.id}>{item.transcript || item.id}</option>)}</select> : <input value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })} />}</Field>
          <Field title="语言"><input value={recipe.language} onChange={event => editRecipe({ language: event.target.value })} /></Field>
          <Field title="默认发声方式"><select value={recipe.default_delivery || 'normal'} onChange={event => editRecipe({ default_delivery: event.target.value as Delivery })}>{styles.map(style => <option key={style.value} value={style.value}>{style.label}</option>)}</select></Field>
          <Field title="默认情绪"><select value={recipe.default_emotion || 'neutral'} onChange={event => editRecipe({ default_emotion: event.target.value })}>{Object.entries(emotionNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
          <Field title="默认句后停顿（毫秒）"><input type="number" min={0} max={30000} step={50} value={recipe.default_pause_ms || 0} onChange={event => editRecipe({ default_pause_ms: Number(event.target.value) })} /></Field>
        </div>
          <div className="grid">{Object.entries(provider?.options_schema.properties || {}).filter(([key]) => key !== 'schema_version').map(([key, field]) => <Field key={key} title={field.title || optionNames[key] || key}>{field.enum ? <select value={String(recipe.provider_options[key] ?? field.default ?? '')} onChange={event => editRecipe({ provider_options: { ...recipe.provider_options, [key]: event.target.value } })}><option value="">默认</option>{field.enum.map(value => <option key={String(value)} value={value}>{value}</option>)}</select> : field.type === 'boolean' ? <input type="checkbox" checked={Boolean(recipe.provider_options[key] ?? field.default)} onChange={event => editRecipe({ provider_options: { ...recipe.provider_options, [key]: event.target.checked } })} /> : <input type={['number', 'integer'].includes(field.type || '') ? 'number' : 'text'} step={field.type === 'integer' ? 1 : 'any'} min={field.minimum} max={field.maximum} title={field.description} value={String(recipe.provider_options[key] ?? field.default ?? '')} onChange={event => { const value = event.target.value; const options = { ...recipe.provider_options }; if (!value) delete options[key]; else options[key] = ['number', 'integer'].includes(field.type || '') ? Number(value) : value; editRecipe({ provider_options: options }) }} />}</Field>)}</div>
          <div className="row"><button onClick={() => { setConnection({ name: '', provider_id: recipe.provider_id, deployment: provider?.connection_required ? 'cloud' : 'local', api_key: '', base_url: '', timeout: 60 }); setShowConnection(!showConnection) }}>新建连接</button><button disabled={!recipe.connection_ref || !!busy} onClick={editConnection}>编辑连接</button><button disabled={!recipe.connection_ref || !!busy} onClick={() => void run('检查连接', async () => setProbeResult(await speechApi.probe(recipe.connection_ref, recipe.model, recipe.mode)))}>检查连接</button><button className="primary" disabled={!!busy || !recipe.name.trim() || !recipe.voice_id || !recipe.provider_id || !recipe.connection_ref} onClick={() => void run('保存配方', saveRecipe)}>保存新修订</button><button disabled={!adoptable} onClick={() => setTab(1)}>编辑演绎 →</button></div>
          {probeResult && <details open><summary>连接检查结果</summary><pre>{json(probeResult)}</pre></details>}{showConnection && <div className="item"><h3>{connection.id ? '编辑' : '新建'} {connectionProvider?.name} 连接</h3><div className="grid"><Field title="连接名称"><input value={connection.name || ''} onChange={event => setConnection({ ...connection, name: event.target.value })} /></Field><Field title="运行位置"><select value={connection.deployment} onChange={event => setConnection({ ...connection, deployment: event.target.value as SpeechConnection['deployment'] })}><option value="local">{connectionProvider?.connection_required ? '本机服务' : '本机'}</option>{connectionProvider?.connection_required && <><option value="lan">局域网</option><option value="cloud">云端</option></>}</select></Field>{connectionProvider?.connection_required && <><Field title="API 地址"><input value={connection.base_url || ''} onChange={event => setConnection({ ...connection, base_url: event.target.value })} /></Field><Field title="API 密钥"><input type="password" autoComplete="off" value={connection.api_key} onChange={event => setConnection({ ...connection, api_key: event.target.value })} /></Field><Field title="超时（秒）"><input type="number" min={1} value={connection.timeout || 60} onChange={event => setConnection({ ...connection, timeout: Number(event.target.value) })} /></Field></>}{connectionProvider && !connectionProvider.remote && <><Field title="模型路径（可选）"><input value={connection.model_path || ''} onChange={event => setConnection({ ...connection, model_path: event.target.value })} /></Field><Field title="设备（可选）"><input value={connection.device || ''} onChange={event => setConnection({ ...connection, device: event.target.value })} /></Field></>}</div><button disabled={!!busy || !connection.name?.trim()} onClick={() => void run('保存连接', async () => { const saved = await speechApi.connection(connection); editRecipe({ connection_ref: saved.id }); setConnection({ ...connection, api_key: '' }); setShowConnection(false); await refresh() })}>保存连接</button></div>}
          {provider && <details style={{ marginTop: 14 }}><summary>引擎能力与验证状态</summary><pre>{json(selectedMode?.capabilities || provider.capabilities)}</pre></details>}
        </section>
        <section className="panel"><div className="row spread"><h2>参考素材</h2><button disabled={!!busy} onClick={() => void run('读取参考音频', inspectReference)}>导入音频</button></div>
          {source && <div className="item"><p className="muted">{source.path} · {source.duration.toFixed(2)} 秒</p>{waveformSvg(source, cropStart, cropEnd)}<audio ref={sourcePlayer} controls src={speechApi.referenceAudio(source.id, true)} onTimeUpdate={() => { if (playingCrop.current && sourcePlayer.current && sourcePlayer.current.currentTime >= cropEnd) { sourcePlayer.current.pause(); playingCrop.current = false } }} /><div className="grid"><Field title="起点（秒）"><input type="number" min={0} max={cropEnd} step={.01} value={cropStart} onChange={event => { setCropStart(Number(event.target.value)); setConfirmed(false) }} /></Field><Field title="终点（秒）"><input type="number" min={cropStart} max={source.duration} step={.01} value={cropEnd} onChange={event => { setCropEnd(Number(event.target.value)); setConfirmed(false) }} /></Field><Field title="语言"><input value={language} onChange={event => setLanguage(event.target.value)} /></Field></div><Field title="选中片段的真实转录"><textarea rows={3} value={transcript} onChange={event => { setTranscript(event.target.value); setConfirmed(false) }} /></Field><label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /> 已核对文字与所选片段一致</label><div className="row" style={{ marginTop: 12 }}><button className="primary" disabled={!!busy || !confirmed || !transcript.trim() || cropEnd <= cropStart || cropEnd > source.duration || cropStart < 0} onClick={() => void run('保存参考素材', async () => { const saved = await speechApi.reference({ path: source.path, start: cropStart, end: cropEnd, transcript, language, confirmed: true }); await refresh(); await openAsset(saved); setSource(null); setNotice('参考素材已保存，可用于声音版本') })}>保存选中片段</button></div></div>}
          {source && <div className="item"><div className="row"><button disabled={!!busy} onClick={() => void run('识别参考台词', () => analyzeSource(false))}>识别参考台词</button><button disabled={!!busy} onClick={() => void run('分离人声与识别', () => analyzeSource(true))}>分离人声并比较</button><button onClick={() => { if (sourcePlayer.current) { playingCrop.current = true; sourcePlayer.current.currentTime = cropStart; void sourcePlayer.current.play().catch(cause => setError(String(cause))) } }}>试听所选片段</button></div><p className="muted">识别结果仅供填写参考转录，保存前仍需人工核对。</p>
            {analyzed && <><div className="grid"><div><h3>原始素材</h3><audio controls src={speechApi.referenceAudio(analyzed.original.id, true)} /></div><div><h3>分析使用的音频</h3><audio controls src={speechApi.referenceAudio(analyzed.analyzed.id, true)} /><button onClick={() => { setSource(analyzed.analyzed); setCropStart(0); setCropEnd(Math.min(10, analyzed.analyzed.duration)); setConfirmed(false); setTranscript('') }}>使用此音轨选段</button></div></div><p className="muted">点击识别片段填入时间与文字，再核对音轨。</p>{analyzed.segments.map((segment, index) => <button key={index} style={{ margin: 4 }} onClick={() => { setSource(analyzed.analyzed); setCropStart(segment.start); setCropEnd(segment.end); setTranscript(segment.text); setConfirmed(false) }}>{segment.start.toFixed(1)}–{segment.end.toFixed(1)}s · {segment.text}</button>)}</>}
          </div>}
          {!library.assets.length && !source && <p className="empty">参考音频会保存为独立素材，供支持参考克隆的引擎使用。</p>}
          {library.assets.map(item => <button key={item.id} style={{ margin: '8px 8px 0 0' }} onClick={() => void run('读取素材', () => openAsset(item))}>{item.transcript?.slice(0, 22) || item.id}</button>)}
          {asset && <div className="item"><h3>{asset.transcript}</h3>{waveform && waveformSvg(waveform)}<p className="muted">已保存片段</p><audio controls src={speechApi.referenceAudio(asset.id)} /><details><summary>对比原始素材</summary><audio controls src={speechApi.referenceAudio(asset.id, true)} /></details></div>}
        </section>
      </div></div>}

      {tab === 1 && <><section className="panel"><div className="row spread"><h2>台词</h2><select aria-label="载入已有方案" value={plan?.id || ''} onChange={event => { const saved = library.plans.find(item => item.id === event.target.value); if (saved) { setPlan(structuredClone(saved)); setScript(saved.text); setPlanDirty(false); setCompiled(null) } }}><option value="">载入已有方案…</option>{library.plans.map(item => <option key={item.id} value={item.id}>{item.text.slice(0, 45)}</option>)}</select></div><textarea aria-label="试音原文" rows={5} value={script} onChange={event => { setScript(event.target.value); setCompiled(null) }} placeholder="输入试音台词。演绎方案保留原文，只调整说话方式和停顿。" /><div className="row" style={{ marginTop: 14 }}><button className="primary" disabled={!!busy || !script.trim()} onClick={() => void run('建立台词方案', createPlan)}>建立新方案</button><button disabled={!!busy || !plan || script !== plan.text || planDirty} onClick={() => void run('自动规划演绎', async () => { if (plan) { const result = await speechApi.planPerformance(plan.id); setPlan(result); setScript(result.text); setPlanDirty(false); setCompiled(null); await refresh() } })}>LLM 自动演绎</button></div>{plan && script !== plan.text && <p className="muted">台词已修改，请建立新方案后继续。</p>}</section>
        {plan && <section className="panel"><h2>逐句演绎</h2>{plan.segments.map((segment, index) => <div className="segment" key={segment.id}><h3>{index + 1}. {segmentText(plan, segment.start, segment.end)}</h3><div className="grid"><Field title="发声方式"><select value={segment.delivery} onChange={event => updateSegment(segment.id, { delivery: event.target.value as Delivery })}>{styles.map(style => <option key={style.value} value={style.value}>{style.label}</option>)}</select></Field><Field title="情绪意图"><select value={segment.emotion} onChange={event => updateSegment(segment.id, { emotion: event.target.value })}>{['neutral', 'happy', 'sad', 'angry', 'excited', 'calm', 'nervous', 'relaxed'].map(emotion => <option key={emotion} value={emotion}>{emotionNames[emotion] || emotion}</option>)}</select></Field><Field title="句后停顿（毫秒）"><input type="number" min={0} max={10000} step={50} value={segment.pause_ms} onChange={event => updateSegment(segment.id, { pause_ms: Number(event.target.value) })} /></Field></div></div>)}<div className="row"><button disabled={!!busy || script !== plan.text} onClick={() => void run('保存演绎方案', async () => { const saved = await speechApi.plan({ text: plan.text, segments: plan.segments }); setPlan(saved); setPlanDirty(false); setCompiled(null); await refresh() })}>保存演绎方案</button><button disabled={!!busy || !adoptable || planDirty || script !== plan.text} onClick={() => void run('检查合成请求', async () => setCompiled((await speechApi.compile(recipe.id, plan.id)).requests))}>检查引擎请求</button><button className="primary" disabled={!!busy || !adoptable || planDirty || script !== plan.text} onClick={() => void run('提交试音', () => generate())}>生成新候选</button></div><p className="muted">当前配方：{recipe.name || '未选择'}。云端生成会调用所选连接，可能计费；检查请求不会合成。</p>{compiled && <details open><summary>实际编译请求（不含密钥）</summary><pre>{json(compiled)}</pre></details>}</section>}
      </>}

      {tab === 2 && <><section className="panel"><div className="row spread"><h2>试音与对比</h2><label><input type="checkbox" checked={equalLoudness} onChange={event => setEqualLoudness(event.target.checked)} /> 校准试听音量</label></div><Field title="试音实验"><select value={experimentId} onChange={event => { setExperimentId(event.target.value); setComparison([]); const exp = library.experiments.find(item => item.id === event.target.value); const saved = library.plans.find(item => item.id === exp?.plan_id); if (saved) { setPlan(saved); setScript(saved.text); setPlanDirty(false) } }}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><div className="row"><span className="muted">配方：{recipe.name || '未选择'}{recipeDirty ? '（未保存）' : ''}</span><button disabled={!!busy || !adoptable || !plan || planDirty || script !== plan.text} onClick={() => void run('生成新候选', () => generate())}>再生成一组</button></div>
          {tasks.map(task => <div className="item" key={task.task_id}><div className="row spread"><span>{task.task_id} · {task.state} · {Math.round(task.progress * 100)}%</span>{['pending', 'running'].includes(task.state) && <button onClick={() => void run('取消任务', async () => { const result = await tasksApi.cancel(task.task_id); setTasks(previous => previous.map(item => item.task_id === result.task_id ? result : item)) })}>取消后续生成</button>}</div>{task.message && <p className="muted">{task.message}</p>}{task.error && <p className="error">{json(task.error)}</p>}</div>)}
        </section>
        {!takes.length && <div className="panel empty">尚无已完成的候选。先保存配方和台词方案，再生成试音；失败或未完成的音频不能采用。</div>}
        {plan?.segments.map((segment, index) => <section className="panel" key={segment.id}><div className="row spread"><h3>第 {index + 1} 句 · {segmentText(plan, segment.start, segment.end)}</h3><button disabled={!!busy || !adoptable || planDirty || script !== plan.text} onClick={() => void run('重生成单句', () => generate(segment.id))}>仅重生成此句</button></div><div className="grid">{takes.filter(take => take.segment_id === segment.id).map(take => <div className="item" key={take.id}><div className="row spread"><strong>{take.id}</strong><label><input type="checkbox" checked={comparison.includes(take.id)} disabled={!comparison.includes(take.id) && (comparison.length >= 2 || comparison.some(id => takes.find(item => item.id === id)?.segment_id !== take.segment_id))} onChange={event => setComparison(event.target.checked ? [...comparison, take.id] : comparison.filter(id => id !== take.id))} /> 对比</label></div><p className="muted">{take.audio?.duration?.toFixed(2) || '—'} 秒 · 生成耗时 {take.elapsed_seconds?.toFixed(1) || '—'} 秒</p><CandidateAudio url={speechApi.takeAudio(take.id)} equalLoudness={equalLoudness} /><div className="row"><button disabled={!!busy} onClick={() => void run('采用候选配方', () => adoptRecipe(take))}>采用此配方</button><button className="primary" disabled={!!busy} onClick={() => void run('采用片段音频', async () => { await speechApi.select({ experiment_id: experimentId, segment_id: take.segment_id, take_id: take.id }); await refresh(); setNotice('已采用该句音频，其余片段保留') })}>{library.selections.some(item => item.experiment_id === experimentId && item.segment_id === segment.id && item.take_id === take.id) ? '已采用音频' : '采用此句音频'}</button></div></div>)}</div></section>)}
        {comparison.length === 2 && <section className="panel"><h2>候选配置差异</h2><div className="grid">{comparison.map(id => { const take = takes.find(item => item.id === id); const other = takes.find(item => item.id === comparison.find(otherId => otherId !== id)); if (!take || !other) return null; const keys = new Set([...Object.keys(take.compiled_request), ...Object.keys(other.compiled_request)]); const diff = Object.fromEntries([...keys].filter(key => json(take.compiled_request[key]) !== json(other.compiled_request[key])).map(key => [key, take.compiled_request[key]])); return <div key={id}><h3>{id}</h3><pre>{Object.keys(diff).length ? json(diff) : '有效配置相同；声音差异可能来自随机生成。'}</pre></div> })}</div></section>}
      </>}

      {tab === 3 && <><section className="panel"><h2>将配方用于正式配音</h2><p>工作台接收当前配方的固定快照，按正式台词重新合成。</p><p className="muted">{recipe.name || '尚未选择配方'} · {recipe.provider_id || '—'} · {recipe.model || '—'} · 修订 {recipe.revision || '—'}</p><button className="primary" disabled={!!busy || !adoptable} onClick={() => void run('创建工作台草稿', async () => { const draft = await speechApi.workbenchDraft(recipe.id); useSpeechDraftStore.getState().setRecipe(draft.recipe); useNavStore.getState().setPage('workbench') })}>送入工作台草稿</button><p className="muted">不会自动提交任务，也不会将试音句音频拼入其他台词。</p></section>
        <section className="panel"><h2>导出本实验采用的音频</h2><p className="muted">逐句采用满意候选后，创建新的组装版本。更换某句候选后需要重新组装。</p><Field title="实验"><select value={experimentId} onChange={event => setExperimentId(event.target.value)}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><button disabled={!!busy || !experimentId} onClick={() => void run('组装已选音频', async () => { await speechApi.assembly(experimentId); await refresh(); setNotice('新的音频组装版本已生成') })}>组装已采用片段</button>{library.assemblies.filter(item => item.experiment_id === experimentId).map(item => <div className="item" key={item.id}><h3>组装版本 {item.revision || item.id}</h3><audio controls src={speechApi.assemblyAudio(item.id)} /><a href={speechApi.assemblyAudio(item.id)} download>下载音频</a></div>)}</section>
      </>}
    </main>
  </div>
}
