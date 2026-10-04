import { confirmAction } from '@/utils/confirmAction'
import SpeechOptionsFields from '@/components/SpeechOptionsFields'
import QwenReferenceMode from '@/components/QwenReferenceMode'
import SpeechConnectionManager from '@/components/SpeechConnectionManager'
import { defaultSpeechConnection } from '@/domain/speechConnections'
import FishVoicePicker from '@/components/FishVoicePicker'
import { speechOptionsIssue } from '@/domain/speechAdvancedOptions'
import { blankSpeechRecipe, recipeFromReference, referenceModes, selectSpeechProvider, selectSpeechMode, selectSpeechModel, speechRecipeCapabilityIssue } from '@/domain/speechRecipeTransitions'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi, speechRecipeDraft } from '@/api/speech'
import type { ReferenceAsset, SpeechConnection, SpeechConnectionDefault, SpeechLibrary, SpeechPlan, SpeechProvider, SpeechRecipe, SpeechTake } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import type { TaskStatusResponse } from '@/api/types'
import ReferenceLibrary from './ReferenceLibrary'
import { useNavStore } from '@/stores/navStore'
import CandidateAudio from './CandidateAudio'
import VoiceRecipeList from './VoiceRecipeList'
import './VoiceLab.css'

const emptyLibrary: SpeechLibrary = { voices: [], recipes: [], assets: [], experiments: [], takes: [], plans: [], selections: [], assemblies: [], connections: [] }
const variantNames = { hosted: '服务端音色 ID', builtin: '内置说话人 ID', reference: '参考素材', design: '声音描述', default: '引擎默认声音' }
const modeNames: Record<string, string> = { default: '引擎默认声音', hosted: '服务端音色', builtin: '内置声音', reference: '参考声音克隆', design: '声音设计' }
const deploymentNames = { local: '本机', lan: '局域网', cloud: '云端' }
const languageNames: Record<string, string> = { auto: '自动（按合成文本识别）', zh: '中文', en: '英语', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', it: '意大利语', pt: '葡萄牙语', ru: '俄语' }
const deliveryNames = { normal: '普通', soft: '轻柔', whisper: '耳语' }
const emotionNames: Record<string, string> = { neutral: '中性', happy: '开心', sad: '悲伤', angry: '生气', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const blankRecipe = blankSpeechRecipe
function Field({ title, children }: { title: string; children: ReactNode }) { return <label className="field">{title}{children}</label> }
function json(value: unknown) { return JSON.stringify(value, null, 2) }
function segmentText(plan: SpeechPlan, start: number, end: number) { return Array.from(plan.text).slice(start, end).join('') }

export default function VoiceLab() {
  const [tab, setTab] = useState(0)
  const [library, setLibrary] = useState<SpeechLibrary>(emptyLibrary)
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [connectionDefaults, setConnectionDefaults] = useState<SpeechConnectionDefault[]>([])
  const [connectionsLoaded, setConnectionsLoaded] = useState(false)
  const catalogGeneration = useRef(0)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [showArchivedRules, setShowArchivedRules] = useState(false)
  const [voiceListOpen, setVoiceListOpen] = useState(false)
  const [voiceQuery, setVoiceQuery] = useState('')
  const [referenceBusy, setReferenceBusy] = useState(false)
  const [ruleList, setRuleList] = useState<SpeechRecipe[]>([])
  const [recipe, setRecipe] = useState<SpeechRecipe>(blankRecipe)
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [retainedReferenceId, setRetainedReferenceId] = useState('')
  const [connection, setConnection] = useState<Partial<SpeechConnection> & { api_key: string }>({ name: '', provider_id: '', deployment: 'cloud', api_key: '', base_url: '', timeout: 60 })
  const [showConnection, setShowConnection] = useState(false)
  const [advancedConnection, setAdvancedConnection] = useState(false)
  const [localResolution, setLocalResolution] = useState<{ key: string; connectionId?: string; pending?: boolean; ready?: boolean; detail: string } | null>(null)
  const [probeResult, setProbeResult] = useState<{ key: string; value: Record<string, unknown> } | null>(null)
  const [script, setScript] = useState('')
  const [plan, setPlan] = useState<SpeechPlan | null>(null)
  const [compiled, setCompiled] = useState<Record<string, unknown>[] | null>(null)
  const [experimentId, setExperimentId] = useState('')
  const [tasks, setTasks] = useState<TaskStatusResponse[]>([])
  const [equalLoudness, setEqualLoudness] = useState(false)
  const [comparison, setComparison] = useState<string[]>([])
  const [presetTakeId, setPresetTakeId] = useState('')
  const [presetName, setPresetName] = useState('')
  const alive = useRef(true)
  const provider = providers.find(item => item.provider_id === recipe.provider_id)
  const connectionProvider = providers.find(item => item.provider_id === connection.provider_id)
  const selectedMode = provider?.modes.find(mode => mode.id === recipe.mode)
  const availableReferenceMode = referenceModes(provider)[0]
  const qwenReference = provider?.provider_id === 'qwen3' && recipe.mode === 'reference' && recipe.model === 'qwen3-base' && provider.options_schema.properties.x_vector_only_mode?.type === 'boolean'
  const experiment = library.experiments.find(item => item.id === experimentId)
  const takes = library.takes.filter(item => item.experiment_id === experimentId)
  const legacyRule = !!recipe.id && (!!library.voices.find(item => item.id === recipe.voice_id)?.bindings.length || recipe.variant.style !== 'normal')
  const adoptable = !!recipe.id && !recipeDirty && !recipe.archived
  const localProvider = provider?.remote === false
  const localKey = JSON.stringify([recipe.provider_id, recipe.model, recipe.mode])
  const currentLocalResolution = localResolution?.key === localKey && (!recipe.connection_ref || localResolution.connectionId === recipe.connection_ref) ? localResolution : null
  const selectedConnection = library.connections.find(item => item.id === recipe.connection_ref)
  const defaultConnection = defaultSpeechConnection(recipe.provider_id, library.connections, connectionDefaults)
  const missingConnection = !!recipe.connection_ref && !selectedConnection && recipe.connection_ref !== `engine-default-${recipe.provider_id}`
  const probeKey = JSON.stringify([recipe.provider_id, recipe.model, recipe.mode, recipe.connection_ref, selectedConnection])
  const currentProbeResult = probeResult?.key === probeKey ? probeResult.value : null
  const engineDefaultConnection = !!provider && !provider.connection_required && recipe.connection_ref === `engine-default-${provider.provider_id}`
  const showConnectionChoice = advancedConnection || (!!provider?.connection_required && !recipe.connection_ref) || (!!recipe.connection_ref && !selectedConnection && !engineDefaultConnection) || (localProvider && !!selectedConnection && selectedConnection.deployment !== 'local')
  const referenceAsset = recipe.variant.kind === 'reference' ? library.assets.find(item => item.id === recipe.variant.value) : undefined
  const retainedReference = library.assets.find(item => item.id === retainedReferenceId)
  const visibleRules = ruleList.filter(item => (showArchivedRules || !item.archived) && (item.name + ' ' + (item.description || '')).toLocaleLowerCase().includes(voiceQuery.toLocaleLowerCase()))
  const sourceRequired = selectedMode?.voice_sources?.required ?? recipe.variant.kind !== 'default'
  const savedLegacyDevice = !!recipe.id && !recipeDirty && (recipe.provider_id === 'qwen3' ? ['cpu', 'cuda:0'] : recipe.provider_id === 'voxcpm2' ? ['auto', 'cpu', 'cuda:0'] : []).includes(String(recipe.provider_options.device))
  const checkedOptions = savedLegacyDevice ? Object.fromEntries(Object.entries(recipe.provider_options).filter(([key]) => key !== 'device')) : recipe.provider_options
  const capabilityIssue = speechRecipeCapabilityIssue(recipe, provider)
  const configurationReason = capabilityIssue || (((provider?.connection_required || localProvider || recipe.connection_ref) && !selectedConnection && !engineDefaultConnection) || (selectedConnection && selectedConnection.provider_id !== provider?.provider_id) ? '请确认属于当前引擎的运行连接。'
    : sourceRequired && !recipe.variant.value.trim() ? '请补充所选方式要求的声音来源。'
    : recipe.variant.kind === 'reference' && (!referenceAsset || referenceAsset.archived) ? '参考录音不存在或已归档。'
    : recipe.provider_id === 'qwen3' && recipe.mode === 'reference' && recipe.provider_options.x_vector_only_mode !== true && (!referenceAsset?.transcript.trim() || !referenceAsset.confirmed) ? '请选择“仅声音特征”，或为“参考音频 + 原文”补充已核对的录音原文。'
    : speechOptionsIssue(provider, recipe.mode, checkedOptions, recipe.model))
  const saveReason = legacyRule ? '历史音色保持只读，可复制为新规则。' : !recipe.name.trim() ? '请填写音色名称。' : configurationReason
  const performance = selectedMode?.capabilities || provider?.capabilities || {}
  const deliveryCapabilities = (performance.delivery || {}) as Record<string, { support?: string }>
  const directDeliveries = Object.keys(deliveryNames).filter(value => value === 'normal' || deliveryCapabilities[value]?.support === 'direct')
  const supportsEmotion = (performance.emotion as { support?: string } | undefined)?.support === 'direct'
  const defaultDelivery = recipe.default_delivery || 'normal'
  const defaultEmotion = recipe.default_emotion || 'neutral'
  const performanceIssue = !directDeliveries.includes(defaultDelivery) && recipe.variant.style !== defaultDelivery ? '当前生成方式不支持此发声方式，请改回普通或选择兼容引擎。'
    : !supportsEmotion && defaultEmotion !== 'neutral' ? '当前生成方式不支持独立情绪参数，请改回中性。' : ''
  const auditionReason = recipe.archived ? '已归档音色需先恢复。' : configurationReason || performanceIssue
  const presetTake = library.takes.find(item => item.id === presetTakeId)
  const recipeInput = () => recipe.id && !recipeDirty ? { recipe_id: recipe.id } : { recipe_draft: { ...speechRecipeDraft(recipe), name: recipe.name.trim() || '未保存试听' } }

  const useReason = recipe.archived ? '已归档音色需先恢复。' : !recipe.id || recipeDirty ? '可先试听当前草稿；保存后可用于工作台。保存不会运行模型。' : '已保存；试听和工作台运行时仍会检查所需模型与连接。'

  const refresh = useCallback(async () => {
    const generation = ++catalogGeneration.current
    const [result, rules, catalog] = await Promise.all([speechApi.library(), speechApi.rules(true), speechApi.connections()])
    if (alive.current && generation === catalogGeneration.current) {
      setLibrary({ ...result, connections: catalog.connections.map(item => ({ ...result.connections.find(detail => detail.id === item.id), ...item })) }); setRuleList(rules.recipes)
      setConnectionDefaults(catalog.defaults || []); setConnectionsLoaded(true)
    }
  }, [])
  useEffect(() => {
    if (!connectionsLoaded || recipe.id || recipe.connection_ref || !recipe.model || !recipe.mode) return
    if (defaultConnection) {
      setRecipe(previous => previous.provider_id === recipe.provider_id && !previous.id && !previous.connection_ref
        ? { ...previous, connection_ref: defaultConnection.id } : previous)
      setRecipeDirty(true)
      return
    }
    if (!localProvider) return
    let active = true
    const { provider_id, model, mode } = recipe
    setLocalResolution({ key: localKey, pending: true, detail: '正在读取此引擎的本机运行配置…' })
    void speechApi.localConnection(provider_id, model, mode).then(async result => {
      if (!active) return
      if (!result.connection) {
        setLocalResolution({ key: localKey, detail: result.detail }); setAdvancedConnection(true)
        const latest = await speechApi.connections()
        if (active) { setLibrary(previous => ({ ...previous, connections: latest.connections.map(item => ({ ...previous.connections.find(detail => detail.id === item.id), ...item })) })); setConnectionDefaults(latest.defaults || []) }
        return
      }
      const resolved = result.connection
      setLocalResolution({ key: localKey, connectionId: resolved.id, ready: result.readiness?.ready,
        detail: [result.readiness?.ready === false ? '尚未就绪：' : '', result.readiness?.detail || '环境状态尚未检查。', ' ', result.detail].join('') })
      setLibrary(previous => ({ ...previous, connections: [...previous.connections.filter(item => item.id !== resolved.id), resolved] }))
      setRecipe(previous => previous.provider_id === provider_id && previous.model === model && previous.mode === mode && !previous.connection_ref && !previous.id
        ? { ...previous, connection_ref: resolved.id } : previous)
      setRecipeDirty(true)
    }).catch(cause => {
      if (active) { setLocalResolution({ key: localKey, detail: '无法准备本机配置：' + String(cause) }); setAdvancedConnection(true) }
    })
    return () => { active = false }
  }, [connectionsLoaded, defaultConnection?.id, localProvider, localKey, recipe.id, recipe.connection_ref, recipe.provider_id, recipe.model, recipe.mode])
  useEffect(() => {
    alive.current = true
    let active = true
    const generation = ++catalogGeneration.current
    void Promise.all([speechApi.providers(), speechApi.library(), tasksApi.list(), speechApi.rules(true), speechApi.connections()]).then(([descriptors, data, taskList, rules, catalog]) => {
      if (!active || !alive.current) return
      // A concurrent catalog refresh does not load engine descriptors or tasks.
      // Keep those initial reads, but never overwrite a newer connection catalog.
      setProviders(descriptors.providers); setTasks(taskList.tasks.filter(task => task.task_type === 'speech.generate'))
      if (generation === catalogGeneration.current) { setLibrary({ ...data, connections: catalog.connections.map(item => ({ ...data.connections.find(detail => detail.id === item.id), ...item })) }); setConnectionDefaults(catalog.defaults || []); setConnectionsLoaded(true); setRuleList(rules.recipes) }
    }).catch(cause => { if (active && alive.current && generation === catalogGeneration.current) setError('无法加载音色实验室：' + String(cause)) })
    return () => { active = false; alive.current = false; catalogGeneration.current++ }
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
  function applyRecipeSelection(next: SpeechRecipe) {
    const removed = Object.keys(recipe.provider_options).filter(key => key !== 'schema_version' && JSON.stringify(recipe.provider_options[key]) !== JSON.stringify(next.provider_options[key]))
    editRecipe(next)
    const issue = speechRecipeCapabilityIssue(next, providers.find(item => item.provider_id === next.provider_id))
    setNotice([issue, removed.length ? '已清理或重置不适用的参数：' + removed.join('、') : '',
      retainedReferenceId && next.variant.kind !== 'reference' ? '参考录音和原文仍保留；当前生成方式不使用录音，切回参考声音克隆可继续使用。' : ''].filter(Boolean).join(' '))
  }
  function changeProvider(id: string) {
    setShowConnection(false); setAdvancedConnection(false); setProbeResult(null); setLocalResolution(null)
    const descriptor = providers.find(item => item.provider_id === id)
    applyRecipeSelection(selectSpeechProvider(recipe, descriptor))
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
    if (auditionReason || !script.trim()) throw new Error(auditionReason || '请填写试音台词')
    const currentPlan = plan && plan.text === script ? plan : await speechApi.plan({ text: script })
    setPlan(currentPlan)
    let id = experimentId
    if (!id || library.plans.find(item => item.id === experiment?.plan_id)?.text_hash !== currentPlan.text_hash) {
      const created = await speechApi.experiment((recipe.name || '试音') + ' · ' + new Date().toLocaleString(), currentPlan.id)
      id = created.id; setExperimentId(id); setComparison([])
    }
    const task = await speechApi.generateDraft(id, recipeInput(), currentPlan.id, segmentId)
    setTasks(previous => [...previous, task]); await refresh(); setTab(2)
    setNotice('已提交新候选任务，已有结果会保留。')
  }
  function useRecipe(item: SpeechRecipe) { setRecipe(structuredClone(item)); setRetainedReferenceId(item.variant.kind === 'reference' ? item.variant.value : ''); setRecipeDirty(false); setCompiled(null); setProbeResult(null); setLocalResolution(null); setAdvancedConnection(false); setShowConnection(false); setVoiceListOpen(false); setNotice('') }
  async function adoptRecipe(take: SpeechTake) {
    const saved = take.recipe_snapshot || library.recipes.find(item => item.id === take.recipe_id)
    if (!saved) throw new Error('此候选的生成配置不可用，不能用当前表单替代历史配置')
    if (recipeDirty && !await confirmAction('当前生成设置尚未保存，使用该候选的冻结配置替换草稿？')) return
    setRecipe({ ...structuredClone(saved), id: '', revision: 0, voice_id: '', archived: false })
    setRetainedReferenceId(saved.variant.kind === 'reference' ? saved.variant.value : '')
    setProbeResult(null); setLocalResolution(null)
    setRecipeDirty(true); setCompiled(null); setNotice('已载入该候选生成时的配置；这是新草稿，已有音色不变。')
  }
  async function saveTakePreset() {
    if (!presetTakeId || !presetName.trim()) throw new Error('请选择试听结果并填写预设名称')
    const saved = await speechApi.ruleFromTake(presetTakeId, presetName.trim())
    await refresh(); setPresetTakeId(''); setPresetName('')
    setNotice(`已保存TTS高级预设“${saved.name}”。可在工作台为兼容引擎选择，当前表单保持不变。`)
  }
  function changeMode(id: string) {
    setProbeResult(null); setLocalResolution(null)
    applyRecipeSelection(selectSpeechMode(recipe, provider, id, retainedReferenceId))
  }
  function changeModel(model: string) {
    setProbeResult(null); setLocalResolution(null)
    applyRecipeSelection(selectSpeechModel(recipe, provider, model))
  }
  function referenceModeField() {
    return qwenReference && <QwenReferenceMode value={recipe.provider_options.x_vector_only_mode === true} onChange={value => editRecipe({ provider_options: { ...recipe.provider_options, x_vector_only_mode: value } })} />
  }
  function targetLanguageField() {
    if (recipe.provider_id === 'fish_audio') return <p className="muted">Fish Audio 按合成文本识别语言，不支持在此强制指定目标语言；请直接输入目标语言的台词。</p>
    return <Field title="合成目标语言"><select value={recipe.language} onChange={event => editRecipe({ language: event.target.value })}>{!languageNames[recipe.language] && <option value={recipe.language}>{recipe.language || '未指定'}（当前值）</option>}{Object.entries(languageNames).map(([code, label]) => <option value={code} key={code}>{label}</option>)}</select></Field>
  }
  function advancedFields() {
    return <>
      {recipe.provider_id === 'qwen3' && recipe.mode === 'reference' && <p className="muted">Qwen Base 的参考克隆本身就是 Zero-shot，无需训练。它不支持用自然语言指令直接控制情绪；生成方式与 VoiceDesign、CustomVoice 不同。</p>}
      {savedLegacyDevice && <p className="muted">历史规则的设备设置会在执行副本中保留。编辑新参数时，请先在连接中设置相应设备，再明确移除旧设备字段；原规则保持不变。</p>}
      <SpeechOptionsFields provider={provider} mode={recipe.mode} model={recipe.model} omit={qwenReference ? ['x_vector_only_mode'] : []} values={checkedOptions} onChange={provider_options => editRecipe({ provider_options: savedLegacyDevice ? { ...provider_options, device: recipe.provider_options.device } : provider_options })} />
      <div className="recipe-fields performance-options">
        {(directDeliveries.length > 1 || defaultDelivery !== 'normal') && <Field title="默认发声方式"><select value={defaultDelivery} onChange={event => editRecipe({ default_delivery: event.target.value as SpeechRecipe['default_delivery'] })}>
          {!directDeliveries.includes(defaultDelivery) && <option value={defaultDelivery}>{deliveryNames[defaultDelivery]}（需要兼容声音来源）</option>}{directDeliveries.map(value => <option key={value} value={value}>{deliveryNames[value as keyof typeof deliveryNames]}</option>)}</select></Field>}
        {(supportsEmotion || defaultEmotion !== 'neutral') && <Field title="默认情绪"><select value={defaultEmotion} onChange={event => editRecipe({ default_emotion: event.target.value })}>{Object.entries(emotionNames).filter(([value]) => supportsEmotion || value === 'neutral' || value === defaultEmotion).map(([value, label]) => <option key={value} value={value} disabled={!supportsEmotion && value !== 'neutral'}>{label}</option>)}</select></Field>}
        {(performance.pause as { support?: string } | undefined)?.support === 'postprocess' && <Field title="句后停顿（毫秒）"><input type="number" min={0} max={30000} step={1} value={recipe.default_pause_ms || 0} onChange={event => editRecipe({ default_pause_ms: Number(event.target.value) })} /></Field>}
      </div>
      {performanceIssue && <p className="error" role="alert">{performanceIssue}</p>}
      <p className="muted">参数按当前引擎执行；设备和模型路径在连接设置中管理。工作台还会按时间轴处理音频，不保证与试听逐字节相同。</p>
    </>
  }

  async function newRecipe() {
    if (recipeDirty && !await confirmAction('当前音色尚未保存，创建新音色将替换草稿。继续？')) return
    setRecipe(blankRecipe()); setRetainedReferenceId(''); setRecipeDirty(false); setCompiled(null); setProbeResult(null); setLocalResolution(null); setShowConnection(false); setAdvancedConnection(false); setNotice(''); setVoiceListOpen(false)
  }
  async function useReference(item: ReferenceAsset) {
    if (recipeDirty && !await confirmAction('当前音色尚未保存，使用此录音创建新音色将替换草稿。继续？')) return
    const draft = recipeFromReference(recipe, item, providers)
    setRecipe(draft); setRetainedReferenceId(item.id)
    setProbeResult(null); setLocalResolution(null)
    setLibrary(previous => ({ ...previous, assets: [...previous.assets.filter(asset => asset.id !== item.id), item] }))
    setRecipeDirty(true); setShowConnection(false); setAdvancedConnection(false); setVoiceListOpen(false); setCompiled(null)
    setTab(1); setNotice('已用此录音创建新音色草稿，原音色不会被覆盖。合成目标语言默认按合成文本识别，可手动选择中文等语言。' + (draft.provider_id ? '' : '参考录音和原文已保留，请选择支持参考克隆的引擎。'))
  }
  async function toggleArchive() {
    const { id, archived } = recipe
    if (archived) await speechApi.restoreRule(id)
    else await speechApi.archiveRule(id)
    setRecipe(previous => previous.id === id ? { ...previous, archived: !archived } : previous)
    await refresh()
    setNotice(archived ? '音色已恢复。' : '音色已归档，可在列表中显示已归档音色后恢复。')
  }

  return <div className="speech-lab">
    <header><div className="page-heading"><div className="page-heading__copy"><h1 className="page-title">声音与音色</h1><p className="page-description">录音素材、生成规则与试音记录独立管理。</p></div><div className="page-heading__actions"><button disabled={!!busy || referenceBusy} onClick={() => void run('刷新', refresh)}>刷新</button></div></div>
      <nav className="tabs" role="tablist" aria-label="声音管理">{['声音库', '我的音色', '试音记录'].map((title, index) => <button key={title} disabled={!!busy} role="tab" aria-selected={tab === index} onClick={() => (() => { document.querySelectorAll<HTMLAudioElement>('.speech-lab audio').forEach(player => player.pause()); setTab(index) })()}>{title}</button>)}</nav>
    </header>
    <main>{error && <div role="alert" className="notice error">{error}</div>}{notice && <div role="status" className="notice">{notice}</div>}{busy && <p role="status" className="muted">{busy}…</p>}
      <div hidden={tab !== 0}><ReferenceLibrary active={tab === 0} assets={library.assets} refresh={refresh} onUse={useReference} onBusy={setReferenceBusy} /></div>
      <fieldset className="lab-fieldset" disabled={!!busy}>
      {tab === 1 && <div className="columns voice-management">
        <button className="voice-list-toggle" aria-expanded={voiceListOpen} aria-controls="voice-rules" onClick={() => setVoiceListOpen(value => !value)}>我的音色 · {visibleRules.length} {voiceListOpen ? '收起' : '展开'}</button>
        <aside id="voice-rules" className={'panel voice-sidebar' + (voiceListOpen ? ' is-open' : '')}>
          <div className="row spread"><h2>我的音色 <span className="reference-count">{visibleRules.length}</span></h2><button onClick={newRecipe}>新建音色</button></div>
          <input aria-label="搜索音色" placeholder="搜索名称或备注" value={voiceQuery} onChange={event => setVoiceQuery(event.target.value)} />
          <label className="voice-archive"><input type="checkbox" checked={showArchivedRules} onChange={event => setShowArchivedRules(event.target.checked)} /> 显示已归档</label>
          {!visibleRules.length && <p className="empty">{voiceQuery ? '没有匹配的音色。' : '尚无音色。可选择参考录音，或描述希望生成的声音。'}</p>}
          <VoiceRecipeList recipes={visibleRules} providers={providers} selectedId={recipe.id}
            onSelect={async item => { if (!recipeDirty || await confirmAction('当前音色尚未保存，放弃草稿并打开此音色？')) useRecipe(item) }} />
        </aside>
        <section className="panel voice-detail">
          <div className="row spread voice-detail-heading"><div><h2>{recipe.name || '新建音色'}</h2><p className="muted">{recipe.archived ? '已归档' : recipeDirty ? '有未保存修改' : recipe.id ? '已保存 · 修订 ' + recipe.revision : '新草稿'} · 音色生成规则</p></div>
            {recipe.id && <details className="voice-more"><summary>更多</summary><button onClick={() => void run(recipe.archived ? '恢复音色' : '归档音色', toggleArchive)}>{recipe.archived ? '恢复音色' : '归档音色'}</button></details>}
          </div>
          {legacyRule && <div className="notice">这是历史音色，原配置保持只读，仍可试听或送入工作台。{['reference', 'design'].includes(recipe.mode) && <button onClick={() => { setRecipe({ ...blankRecipe(), name: recipe.name + '（副本）', provider_id: recipe.provider_id, model: recipe.model, mode: recipe.mode, connection_ref: recipe.connection_ref, variant: { ...recipe.variant, style: 'normal' }, language: recipe.language, provider_options: { ...recipe.provider_options } }); setRecipeDirty(true); setNotice('已创建独立草稿，不继承旧的发声、情绪或停顿默认值。') }}>复制为新规则</button>}</div>}
          <fieldset className="lab-fieldset" disabled={legacyRule}>
            <section className="recipe-section"><h3>基本信息</h3><div className="recipe-fields">
              <Field title="音色名称"><input value={recipe.name} onChange={event => editRecipe({ name: event.target.value })} /></Field>
              {targetLanguageField()}
              {recipe.provider_id !== 'fish_audio' && <p className="muted recipe-wide">这里选择要生成的语音语言，与参考录音语言独立。例如日语录音配中文台词，合成目标选中文，参考原文仍保留日语。保存的旧音色保持原值，不会自动改语言。</p>}
              <div className="recipe-wide"><Field title="备注（可选）"><input value={recipe.description || ''} onChange={event => editRecipe({ description: event.target.value })} /></Field></div>
            </div></section>
            <section className="recipe-section"><h3>生成方式</h3><div className="recipe-fields">
              <Field title="引擎"><select value={recipe.provider_id} onChange={event => changeProvider(event.target.value)}><option value="">选择引擎</option>{providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}{recipe.variant.kind === 'reference' && recipe.variant.value && !referenceModes(item).length ? '（不支持参考克隆）' : ''}</option>)}</select></Field>
              <Field title="生成方式"><select value={recipe.mode} onChange={event => changeMode(event.target.value)}><option value="">选择方式</option>{provider?.modes.map(mode => <option key={mode.id} value={mode.id}>{modeNames[mode.id] || mode.id}{provider?.provider_id === 'qwen3' && mode.id === 'reference' ? '（Zero-shot）' : ''}</option>)}</select></Field>
              <Field title="模型">{selectedMode?.models.length ? <select value={recipe.model} onChange={event => changeModel(event.target.value)}>{recipe.model && !selectedMode.models.includes(recipe.model) && <option value={recipe.model}>{recipe.model}（已保存）</option>}{selectedMode.models.map(model => <option key={model} value={model}>{model}</option>)}</select> : <input value={recipe.model} disabled={!selectedMode} placeholder={selectedMode ? '填写服务文档中的模型 ID' : '请先选择兼容引擎与生成方式'} onChange={event => changeModel(event.target.value)} />}</Field>
              <Field title={variantNames[recipe.variant.kind]}>{recipe.variant.kind === 'reference' ? <select value={recipe.variant.value} onChange={event => { setRetainedReferenceId(event.target.value); editRecipe({ variant: { ...recipe.variant, value: event.target.value } }) }}><option value="">选择声音库录音</option>{library.assets.filter(item => !item.archived || item.id === recipe.variant.value).map(item => <option key={item.id} value={item.id}>{item.name || item.transcript || item.id}{item.archived ? '（已归档）' : ''}</option>)}</select>  : recipe.variant.kind === 'default' ? <span className="muted">使用引擎默认声音，无需填写音色 ID。</span> : selectedMode?.voice_sources?.presets.length && !selectedMode.voice_sources.allow_custom ? <select value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })}>
                {!selectedMode.voice_sources.presets.some(item => item.id === recipe.variant.value) && <option value={recipe.variant.value}>{recipe.variant.value || '选择声音'}（待确认）</option>}{selectedMode.voice_sources.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}{item.language ? ' · ' + (languageNames[item.language] || item.language) : ''}</option>)}</select>
                : recipe.variant.kind === 'design' ? <textarea rows={3} value={recipe.variant.value} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })} />
                : <input value={recipe.variant.value} placeholder={selectedMode?.voice_sources?.description || '填写真实音色 ID'} onChange={event => editRecipe({ variant: { ...recipe.variant, value: event.target.value } })} />}</Field>
            </div>{capabilityIssue && <p className="notice" role="status">{capabilityIssue}</p>}
            {retainedReference && recipe.variant.kind !== 'reference' && <p className="notice">参考录音“{retainedReference.name || '未命名录音'}”及原文已保留，当前生成方式不使用这段录音。{availableReferenceMode && <button type="button" onClick={() => changeMode(availableReferenceMode.id)}>返回参考声音克隆</button>}</p>}
            {provider?.provider_id === 'fish_audio' && recipe.mode === 'hosted' && <FishVoicePicker connectionId={recipe.connection_ref} value={recipe.variant.value} onSelect={value => editRecipe({ variant: { ...recipe.variant, value } })} />}
            {recipe.variant.kind === 'reference' && <div className="recipe-reference">
              {referenceAsset ? <><div className="row spread"><span>{referenceAsset.name || '参考录音'} · 参考录音语言：{referenceAsset.language === 'auto' ? '未明确' : languageNames[referenceAsset.language] || referenceAsset.language} · {(referenceAsset.duration || 0).toFixed(1)} 秒</span><button onClick={() => setTab(0)}>管理录音</button></div><audio key={referenceAsset.id} controls preload="none" src={speechApi.referenceAudio(referenceAsset.id)} /><p className="muted">参考录音原文（保持录音中的语言）</p><p className="reference-inline-transcript">{referenceAsset.transcript || '未填写原文；所选引擎可能要求参考原文。'}</p></> : <div className="row"><span className="muted">{library.assets.length ? '选择已保存的录音，可在这里试听。' : '声音库为空，请先导入并保存录音。'}</span><button onClick={() => setTab(0)}>导入或管理录音</button></div>}
            </div>}
            {referenceModeField()}</section>
            <section className="recipe-section"><h3>运行设置</h3>
              <div className="row spread connection-summary"><strong>{localProvider ? '本机运行' : provider?.connection_required ? '服务连接' : '引擎运行'}{selectedConnection ? ' · ' + selectedConnection.name + (defaultConnection?.id === selectedConnection.id ? '（此引擎默认）' : '') : missingConnection ? ' · 原连接已缺失，需重选' : engineDefaultConnection ? ' · 引擎默认配置' : provider?.connection_required || localProvider ? ' · 待选择' : ' · 无需独立连接'}</strong><button type="button" aria-expanded={showConnectionChoice} onClick={() => { setAdvancedConnection(!showConnectionChoice); setShowConnection(false) }}>高级连接设置</button></div>
              <p className="muted" role="status">{localProvider ? currentLocalResolution?.detail || '保存音色只保存配置，不代表模型已可运行。可在高级连接设置中检查模型与运行环境。' : selectedConnection ? '已选择连接；保存不代表服务已就绪，可展开设置检查。' : provider?.connection_required ? '请选择明确的服务连接；多个连接不会自动代选。' : '此引擎无需独立连接，实际可用性在执行时检查。'}</p>
              {localProvider && selectedConnection?.model_path && <p className="muted">当前连接使用固定模型路径。切换模型或生成方式后，请核对连接中的模型是否兼容；应用不会自动改写此路径。</p>}
              {showConnectionChoice && <div className="connection-controls"><Field title="连接"><select value={recipe.connection_ref} onChange={event => { setProbeResult(null); setLocalResolution(null); editRecipe({ connection_ref: event.target.value }) }}><option value="" disabled>选择明确的运行连接</option>{missingConnection && <option value={recipe.connection_ref}>原连接已缺失：{recipe.connection_ref}</option>}{provider && !provider.connection_required && <option value={`engine-default-${provider.provider_id}`}>明确使用引擎默认环境</option>}{library.connections.filter(item => item.provider_id === recipe.provider_id).map(item => <option key={item.id} value={item.id}>{item.name} · {deploymentNames[item.deployment]}</option>)}</select></Field><div className="row">
                {provider?.connection_required ? <button onClick={async () => { if (!recipeDirty || await confirmAction('当前音色修改尚未保存，离开并管理外部服务？')) useNavStore.getState().openEngines('external') }}>管理外部语音服务</button> : <><button onClick={() => { setConnection({ name: '', provider_id: recipe.provider_id, deployment: 'local', api_key: '', base_url: '', timeout: 60 }); setShowConnection(!showConnection) }}>新建连接</button><button disabled={!selectedConnection || !!busy} onClick={editConnection}>编辑连接</button></>}
                <button disabled={!selectedConnection && !engineDefaultConnection || !!busy} onClick={() => void run('检查连接', async () => setProbeResult({ key: probeKey, value: await speechApi.probe(recipe.connection_ref, recipe.model, recipe.mode) }))}>检查连接</button>
              </div></div>}
              {showConnectionChoice && <SpeechConnectionManager connections={library.connections} defaults={connectionDefaults} providers={providers} providerId={recipe.provider_id} disabled={!!busy} onChanged={async () => { setProbeResult(null); setLocalResolution(null); await refresh() }} />}
              {currentProbeResult && <details open><summary>连接检查结果</summary><pre>{json(currentProbeResult)}</pre></details>}{showConnection && !connectionProvider?.connection_required && <div className="item"><h3>{connection.id ? '编辑' : '新建'} {connectionProvider?.name} 连接</h3><div className="recipe-fields"><Field title="连接名称"><input value={connection.name || ''} onChange={event => setConnection({ ...connection, name: event.target.value })} /></Field><Field title="运行位置"><select value={connection.deployment} onChange={event => setConnection({ ...connection, deployment: event.target.value as SpeechConnection['deployment'] })}><option value="local">{connectionProvider?.connection_required ? '本机服务' : '本机'}</option>{connectionProvider?.connection_required && <><option value="lan">局域网</option><option value="cloud">云端</option></>}</select></Field>{connectionProvider?.connection_required && <><Field title="API 地址"><input value={connection.base_url || ''} onChange={event => setConnection({ ...connection, base_url: event.target.value })} /></Field><Field title="API 密钥"><input type="password" autoComplete="off" value={connection.api_key} onChange={event => setConnection({ ...connection, api_key: event.target.value })} /></Field><Field title="超时（秒）"><input type="number" min={1} value={connection.timeout || 60} onChange={event => setConnection({ ...connection, timeout: Number(event.target.value) })} /></Field></>}{connectionProvider && !connectionProvider.remote && <><Field title="模型路径（可选）"><input value={connection.model_path || ''} onChange={event => setConnection({ ...connection, model_path: event.target.value })} /></Field><Field title="设备（可选）"><input value={connection.device || ''} onChange={event => setConnection({ ...connection, device: event.target.value })} /></Field></>}</div><button disabled={!!busy || !connection.name?.trim() || !!connection.id && !library.connections.some(item => item.id === connection.id)} onClick={() => void run('保存连接', async () => { const saved = await speechApi.connection(connection); setProbeResult(null); setLocalResolution(null); editRecipe({ connection_ref: saved.id }); setConnection({ ...connection, api_key: '' }); setShowConnection(false); await refresh() })}>保存连接</button></div>}
              {provider && <details className="recipe-advanced"><summary>高级生成参数</summary>{advancedFields()}</details>}
              {provider && <details className="recipe-capabilities"><summary>引擎能力与验证状态</summary><pre>{json(selectedMode?.capabilities || provider.capabilities)}</pre></details>}
            </section>
          </fieldset>
          <div className="recipe-actions"><div className="row">
            {!legacyRule && <button className="primary" disabled={!!busy || !!saveReason || !!performanceIssue} onClick={() => void run('保存音色', saveRecipe)}>保存音色</button>}
            <button disabled={!!auditionReason} onClick={() => setTab(2)}>试音（可选）</button>
            <button disabled={!adoptable} onClick={() => void run('打开工作台', async () => { await speechApi.workbenchDraft(recipe.id); useNavStore.getState().setPage('workbench') })}>前往工作台选择</button>
          </div>{saveReason && !legacyRule && <p className="muted">{saveReason}</p>}{auditionReason && <p className="muted">{auditionReason}</p>}<p className="muted">{useReason} {adoptable && '在工作台打开目标语音合成节点的参数，再从音色预设中选择此音色；不会自动覆盖现有节点。'}</p></div>
        </section>
      </div>}

      {tab === 2 && <section className="panel audition-editor"><h2>新试音</h2>
        <Field title="载入已保存音色或TTS高级预设"><select value={recipe.id} onChange={async event => { const item = ruleList.find(value => value.id === event.target.value); if (item && (!recipeDirty || await confirmAction('当前试听设置尚未保存，载入其他预设？'))) useRecipe(item) }}><option value="">当前未保存草稿</option>{recipe.id && !ruleList.some(item => item.id === recipe.id) && <option value={recipe.id}>{recipe.name}（历史修订）</option>}{ruleList.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name} · r{item.revision}</option>)}</select></Field>
        <p className="muted">{recipe.name || '未命名草稿'} · {provider?.name || '未选引擎'} · {modeNames[recipe.mode] || '未选方式'}{recipeDirty || !recipe.id ? ' · 本次使用草稿快照' : ' · 已保存修订'} <button type="button" onClick={() => setTab(1)}>编辑声音来源</button></p>
        {targetLanguageField()}
        {recipe.provider_id !== 'fish_audio' && <p className="muted">合成目标语言用于下面的试听台词，保存后也用于此音色预设。{referenceAsset && <>参考录音语言：{referenceAsset.language === 'auto' ? '未明确' : languageNames[referenceAsset.language] || referenceAsset.language}；参考原文保持不变。</>}</p>}
        {referenceModeField()}
        <textarea aria-label="试音原文" rows={4} value={script} onChange={event => { setScript(event.target.value); setCompiled(null) }} placeholder="输入要合成的新台词，例如中文配音文本" />
        {provider && <details className="recipe-advanced"><summary>试听高级选项</summary>{advancedFields()}</details>}
        <div className="row" style={{ marginTop: 14 }}><button className="primary" disabled={!!busy || !!auditionReason || !script.trim()} onClick={() => void run('提交试音', () => generate())}>生成试音</button></div>
        {auditionReason && <p className="error" role="status">{auditionReason}</p>}
        <p className="muted">无需先保存改动；每次试音固定当时的设置。试听满意后，在对应候选结果上“保存为TTS高级预设”。云端服务可能计费。</p>
        <details><summary>检查请求（不合成）</summary><button disabled={!!auditionReason || !script.trim()} onClick={() => void run('检查合成请求', async () => { const current = plan?.text === script ? plan : await speechApi.plan({ text: script }); setPlan(current); setCompiled((await speechApi.compileDraft(recipeInput(), current.id)).requests) })}>检查引擎请求（不合成）</button>{compiled && <pre>{json(compiled)}</pre>}</details>
      </section>}

      {tab === 2 && <><section className="panel"><div className="row spread"><h2>试音与对比</h2><label><input type="checkbox" checked={equalLoudness} onChange={event => setEqualLoudness(event.target.checked)} /> 校准试听音量</label></div><Field title="试音实验"><select value={experimentId} onChange={event => { setExperimentId(event.target.value); setComparison([]); const exp = library.experiments.find(item => item.id === event.target.value); const saved = library.plans.find(item => item.id === exp?.plan_id); if (saved) { setPlan(saved); setScript(saved.text); setCompiled(null) } }}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><div className="row"><span className="muted">音色：{recipe.name || '未选择'}{recipeDirty ? '（未保存）' : ''}</span><button disabled={!!busy || !!auditionReason || !plan || script !== plan.text} onClick={() => void run('生成新候选', () => generate())}>再生成一组</button></div>
          {tasks.map(task => <div className="item" key={task.task_id}><div className="row spread"><span>{task.task_id} · {task.state} · {Math.round(task.progress * 100)}%</span>{['pending', 'running'].includes(task.state) && <button onClick={() => void run('取消任务', async () => { const result = await tasksApi.cancel(task.task_id); setTasks(previous => previous.map(item => item.task_id === result.task_id ? result : item)) })}>取消后续生成</button>}</div>{task.message && <p className="muted">{task.message}</p>}{task.error && <p className="error">{json(task.error)}</p>}</div>)}
        </section>
        {!takes.length && <div className="panel empty">尚无已完成的候选。选择音色并输入台词后即可生成试音；失败或未完成的音频不能采用。</div>}
        {plan?.segments.map((segment, index) => <section className="panel" key={segment.id}><div className="row spread"><h3>第 {index + 1} 句 · {segmentText(plan, segment.start, segment.end)}</h3><button disabled={!!busy || !!auditionReason || script !== plan.text} onClick={() => void run('重生成单句', () => generate(segment.id))}>仅重生成此句</button></div><div className="grid">{takes.filter(take => take.segment_id === segment.id).map(take => <div className="item" key={take.id}><div className="row spread"><strong>{take.id}</strong><label><input type="checkbox" checked={comparison.includes(take.id)} disabled={!comparison.includes(take.id) && (comparison.length >= 2 || comparison.some(id => takes.find(item => item.id === id)?.segment_id !== take.segment_id))} onChange={event => setComparison(event.target.checked ? [...comparison, take.id] : comparison.filter(id => id !== take.id))} /> 对比</label></div><p className="muted">{take.audio?.duration?.toFixed(2) || '—'} 秒 · 生成耗时 {take.elapsed_seconds?.toFixed(1) || '—'} 秒</p><CandidateAudio url={speechApi.takeAudio(take.id)} equalLoudness={equalLoudness} /><div className="row"><button disabled={!!busy} onClick={() => void run('采用候选配方', () => adoptRecipe(take))}>载入生成设置</button><button disabled={!!busy || take.status !== 'completed'} onClick={() => { setPresetTakeId(take.id); setPresetName((take.recipe_snapshot?.name || library.recipes.find(item => item.id === take.recipe_id)?.name || 'TTS') + ' · 高级预设') }}>保存为TTS高级预设</button><button className="primary" disabled={!!busy} onClick={() => void run('采用片段音频', async () => { await speechApi.select({ experiment_id: experimentId, segment_id: take.segment_id, take_id: take.id }); await refresh(); setNotice('已采用该句音频，其余片段保留') })}>{library.selections.some(item => item.experiment_id === experimentId && item.segment_id === segment.id && item.take_id === take.id) ? '已采用音频' : '采用此句音频'}</button></div></div>)}</div></section>)}
        {presetTake && <section className="panel take-preset-save"><h3>保存所选试听结果的设置</h3><p className="muted">候选 {presetTake.id} · {presetTake.recipe_snapshot?.name || presetTake.recipe_id}。只保存该候选生成时的冻结配置，不读取当前表单后续修改，也不保存音频或凭据。</p><Field title="TTS高级预设名称"><input value={presetName} maxLength={100} onChange={event => setPresetName(event.target.value)} /></Field><div className="row"><button className="primary" disabled={!!busy || !presetName.trim()} onClick={() => void run('保存TTS高级预设', saveTakePreset)}>保存所选结果的设置</button><button disabled={!!busy} onClick={() => setPresetTakeId('')}>取消</button></div></section>}
        {comparison.length === 2 && <section className="panel"><h2>候选配置差异</h2><div className="grid">{comparison.map(id => { const take = takes.find(item => item.id === id); const other = takes.find(item => item.id === comparison.find(otherId => otherId !== id)); if (!take || !other) return null; const keys = new Set([...Object.keys(take.compiled_request), ...Object.keys(other.compiled_request)]); const diff = Object.fromEntries([...keys].filter(key => json(take.compiled_request[key]) !== json(other.compiled_request[key])).map(key => [key, take.compiled_request[key]])); return <div key={id}><h3>{id}</h3><pre>{Object.keys(diff).length ? json(diff) : '有效配置相同；声音差异可能来自随机生成。'}</pre></div> })}</div></section>}
      </>}

      {tab === 2 && <>
        <section className="panel"><h2>导出本实验采用的音频</h2><p className="muted">逐句采用满意候选后，创建新的组装版本。更换某句候选后需要重新组装。</p><Field title="实验"><select value={experimentId} onChange={event => setExperimentId(event.target.value)}><option value="">选择实验</option>{library.experiments.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><button disabled={!!busy || !experimentId} onClick={() => void run('组装已选音频', async () => { await speechApi.assembly(experimentId); await refresh(); setNotice('新的音频组装版本已生成') })}>组装已采用片段</button>{library.assemblies.filter(item => item.experiment_id === experimentId).map(item => <div className="item" key={item.id}><h3>组装版本 {item.revision || item.id}</h3><audio controls src={speechApi.assemblyAudio(item.id)} /><a href={speechApi.assemblyAudio(item.id)} download>下载音频</a></div>)}</section>
      </>}
      </fieldset>
    </main>
  </div>
}
