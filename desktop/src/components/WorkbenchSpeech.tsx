import { useEffect, useId, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, SpeechConnection, SpeechProvider, SpeechRecipe, WorkbenchSpeechSource } from '@/api/speech'
import type { StageProfileRequest } from '@/api/types'
import { compatibleSpeechRules, initialSpeechEngine } from '@/domain/workbenchSpeech'
import { speechLanguageMatches, speechOptionsIssue } from '@/domain/speechAdvancedOptions'
import { useSpeechDraftStore } from '@/stores/speechDraftStore'
import type { SpeechEngineDraft } from '@/stores/speechDraftStore'
import { useNavStore } from '@/stores/navStore'
import './WorkbenchSpeech.css'
import FishVoicePicker from './FishVoicePicker'
import SpeechOptionsFields from './SpeechOptionsFields'

export interface WorkbenchSpeechResolution {
  stage: StageProfileRequest | null
  error: string
  summary: string
  recipe?: SpeechRecipe
}
const modeNames: Record<string, string> = { default: '引擎默认声音', builtin: '预设声音', hosted: '服务端音色', reference: '参考录音克隆', design: '声音描述' }
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="workbench-speech-field"><span>{label}</span>{children}</label>
}
function legacySavedDevice(recipe: SpeechRecipe | undefined): string | undefined {
  if (!recipe?.id) return undefined
  const allowed = recipe.provider_id === 'qwen3' ? ['cpu', 'cuda:0']
    : recipe.provider_id === 'voxcpm2' ? ['auto', 'cpu', 'cuda:0'] : []
  const device = recipe.provider_options.device
  return typeof device === 'string' && allowed.includes(device) ? device : undefined
}

export default function WorkbenchSpeech({ disabled, language, preferredProvider, onChange }: {
  disabled: boolean
  language: string
  preferredProvider: string
  onChange: (resolution: WorkbenchSpeechResolution) => void
}) {
  const { engine, recipeId, recipe: draftRecipe, setEngine, setRecipe } = useSpeechDraftStore()
  const presetListId = useId()
  const setPage = useNavStore(state => state.setPage)
  const openEngines = useNavStore(state => state.openEngines)
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [recipes, setRecipes] = useState<SpeechRecipe[]>([])
  const [assets, setAssets] = useState<ReferenceAsset[]>([])
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [catalogError, setCatalogError] = useState('')
  const [libraryError, setLibraryError] = useState('')
  const [reload, setReload] = useState(0)
  // A selection is only a preview; applying it is a separate user action.
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [applyNotice, setApplyNotice] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.allSettled([speechApi.providers(), speechApi.library(), speechApi.rules()]).then(([catalog, library, rules]) => {
      if (cancelled) return
      if (catalog.status === 'fulfilled') {
        setProviders(catalog.value.providers)
        setCatalogError('')
        if (!useSpeechDraftStore.getState().engine) {
          const provider = catalog.value.providers.find(item => item.provider_id === preferredProvider) ?? catalog.value.providers[0]
          if (provider) {
            const next = initialSpeechEngine(provider)
            setEngine(next)
          }
        }
      } else {
        setProviders([])
        setCatalogError(`引擎能力加载失败：${String(catalog.reason)}`)
      }
      if (library.status === 'fulfilled') {
        setAssets(library.value.assets.filter(item => !item.archived))
        setConnections(library.value.connections)
        setLibraryError('')
      } else {
        setAssets([]); setConnections([])
        setLibraryError('保存的规则、参考录音和服务连接暂时无法加载，可刷新重试。')
      }
      setRecipes(rules.status === 'fulfilled' ? rules.value.recipes.filter(item => !item.archived) : [])
      if (rules.status === 'rejected') setLibraryError('自定义规则暂时无法加载，可继续使用引擎声音或刷新重试。')
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [reload, preferredProvider, setEngine])

  const provider = providers.find(item => item.provider_id === engine?.providerId)
  const models = [...new Set(provider?.modes.flatMap(mode => mode.models) ?? [])]
  const modes = provider?.modes.filter(mode => !mode.models.length || mode.models.includes(engine?.model ?? '')) ?? []
  const mode = modes.find(item => item.id === engine?.mode)
  const compatibleRules = compatibleSpeechRules(provider, engine?.model ?? '', recipes)
  const selectedRecipe = compatibleRules.find(item => item.id === recipeId)
  const matchingConnections = connections.filter(item => item.provider_id === provider?.provider_id)
  const catalog = mode?.voice_sources
  const previewRecipe = compatibleRules.find(item => item.id === previewId)
  const legacyDevice = legacySavedDevice(previewRecipe ?? selectedRecipe)

  function sourceIssue(modeId: string, value: string, connectionRef: string, values: Record<string, unknown>) {
    if (!provider) return '请选择可用的配音引擎'
    const implicitConnection = !provider.connection_required && (!connectionRef || connectionRef === `engine-default-${provider.provider_id}`)
    if (!implicitConnection && !matchingConnections.some(item => item.id === connectionRef)) {
      return '预设或声音配置的连接已不存在，或不属于当前引擎；请重新选择明确的连接。'
    }
    if (modeId === 'reference') {
      const asset = assets.find(item => item.id === value)
      if (!asset) return '参考录音已不存在或已归档，请选择声音库中可用的录音。'
      const descriptor = provider.modes.find(item => item.id === modeId)
      const reference = (descriptor?.capabilities?.reference ?? provider.capabilities.reference) as { transcript_required?: boolean } | undefined
      const requiresText = reference?.transcript_required || provider.provider_id === 'qwen3'
      const textOptional = provider.provider_id === 'qwen3' && values.x_vector_only_mode === true
      if (requiresText && !textOptional && !asset.transcript.trim()) return '当前参考克隆需要录音原文，请先在声音库补充；Qwen 可显式启用“仅使用声音特征”。'
      if (requiresText && !textOptional && asset.confirmed !== true) return '当前参考克隆需要已核对的录音原文，请先在声音库确认；Qwen 可显式启用“仅使用声音特征”。'
    }
    return speechOptionsIssue(provider, modeId, values, engine?.model ?? '')
  }

  function recipeIssue(item: SpeechRecipe | undefined) {
    if (!item || !compatibleRules.some(rule => rule.id === item.id)) return '原 TTS 高级预设已不可用或与当前引擎、模型不兼容，请重新选择。'
    if (!speechLanguageMatches(item.language, language)) return `预设语言 ${item.language} 与工作台目标语言 ${language} 不一致；请选择匹配的预设或自行修改目标语言，不会自动替换。`
    const descriptor = provider?.modes.find(value => value.id === item.mode)
    if (!item.variant.value.trim() && (descriptor?.voice_sources?.required || ['reference', 'design', 'hosted', 'builtin'].includes(item.variant.kind))) return '预设缺少声音来源，请在声音与音色中补充后保存。'
    // The execution service migrates this legacy field from saved recipes into
    // its connection copy. Do not mutate the recipe or allow it in new inputs.
    const values = legacySavedDevice(item) === undefined ? item.provider_options
      : Object.fromEntries(Object.entries(item.provider_options).filter(([key]) => key !== 'device'))
    return sourceIssue(item.mode, item.variant.value, item.connection_ref, values)
  }
  const previewIssue = previewId ? recipeIssue(previewRecipe) : ''

  const resolution = useMemo<WorkbenchSpeechResolution>(() => {
    const invalid = (error: string): WorkbenchSpeechResolution => ({ stage: null, error, summary: provider?.name ?? '待选择引擎' })
    if (loading) return invalid('正在加载配音能力…')
    if (catalogError) return invalid(catalogError)
    if (!engine || !provider) return invalid('请选择可用的配音引擎')
    if (!engine.model.trim()) return invalid('请根据服务文档填写模型 ID')
    if (recipeId) {
      const issue = recipeIssue(selectedRecipe)
      if (issue || !selectedRecipe) return invalid(issue)
      if (draftRecipe && draftRecipe.revision !== selectedRecipe.revision) return invalid('此 TTS 高级预设已有新修订，请重新预览并应用后再使用。')
      return {
        stage: { enabled: true, provider: provider.provider_id, model: engine.model,
          options: { language, speech_recipe_id: selectedRecipe.id }, provider_options: {} },
        error: '', summary: `${provider.name} · ${selectedRecipe.name} · r${selectedRecipe.revision}`, recipe: selectedRecipe,
      }
    }
    if (!mode || !mode.voice_sources) return invalid('当前引擎未提供声音来源能力，请刷新或选择其他模型')
    const issue = sourceIssue(mode.id, engine.value, engine.connectionRef, engine.providerOptions)
    if (issue) return invalid(issue)
    if (mode.voice_sources.required && !engine.value.trim()) return invalid(mode.voice_sources.description || '请补齐声音来源')
    if (mode.id === 'reference' && !assets.some(item => item.id === engine.value)) return invalid('请选择声音库中可用的参考录音')
    if (mode.voice_sources.presets.length && !mode.voice_sources.allow_custom && !mode.voice_sources.presets.some(item => item.id === engine.value)) return invalid('请选择该引擎提供的预设声音')
    const kind = mode.variant_kinds[0]
    if (!kind) return invalid('该模式未声明支持的声音来源')
    const source: WorkbenchSpeechSource = {
      mode: mode.id, variant: { kind, value: engine.value.trim() || mode.voice_sources.default || '' },
      provider_options: { schema_version: 1, ...engine.providerOptions },
      ...(engine.connectionRef ? { connection_ref: engine.connectionRef } : {}),
    }
    const voiceName = mode.voice_sources.presets.find(item => item.id === engine.value)?.name
      || (mode.id === 'reference' ? assets.find(item => item.id === engine.value)?.name : undefined)
      || (mode.id === 'default' ? '默认声音' : mode.id === 'design' ? '声音描述' : engine.value)
    return { stage: { enabled: true, provider: provider.provider_id, model: engine.model,
      options: { language, speech_source: source }, provider_options: {} }, error: '', summary: `${provider.name} · ${voiceName}` }
  }, [engine, provider, mode, loading, catalogError, recipeId, draftRecipe, selectedRecipe, language, assets, connections])

  useEffect(() => { onChange(resolution) }, [resolution, onChange])

  const edit = (patch: Partial<SpeechEngineDraft>) => { if (engine) setEngine({ ...engine, ...patch }) }
  const changeModel = (model: string) => {
    if (!provider || !engine) return
    const next = initialSpeechEngine(provider, model)
    setPreviewId(null); setApplyNotice('')
    setEngine({ ...next, connectionRef: engine.connectionRef })
  }
  const applyPreview = () => {
    if (previewId === null || !engine) return
    if (previewId) {
      const issue = recipeIssue(previewRecipe)
      if (issue || !previewRecipe) { setApplyNotice(issue); return }
      setRecipe(previewRecipe)
      setApplyNotice(`已应用 ${previewRecipe.name} · r${previewRecipe.revision}；未启动任务。`)
    } else {
      setEngine({ ...engine })
      setApplyNotice('已改为直接配置引擎声音，保留当前声音和引擎参数；未启动任务。')
    }
    setPreviewId(null)
  }

  return <div className="workbench-speech">
    <fieldset disabled={disabled || loading}>
      <div className="workbench-speech-grid">
        <Field label="配音引擎"><select value={engine?.providerId ?? ''} onChange={event => {
          const next = providers.find(item => item.provider_id === event.target.value)
          if (next) { setPreviewId(null); setApplyNotice(''); setEngine(initialSpeechEngine(next)) }
        }}><option value="">选择引擎</option>{providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
          {engine && !provider && <option value={engine.providerId}>{engine.providerId}（暂不可用）</option>}
        </select></Field>
        <Field label={models.length ? '配音模型' : '模型 ID'}>{models.length ? <select value={engine?.model ?? ''} onChange={event => changeModel(event.target.value)}>
          {engine && !models.includes(engine.model) && <option value={engine.model}>{engine.model || '选择模型'}（待确认）</option>}
          {models.map(model => <option key={model} value={model}>{model}</option>)}
        </select> : <input value={engine?.model ?? ''} placeholder="填写服务文档中的模型 ID" onChange={event => changeModel(event.target.value)} />}</Field>
        <Field label="TTS 高级预设"><select value={previewId ?? recipeId ?? ''} onChange={event => { setPreviewId(event.target.value); setApplyNotice('') }}>
          <option value="">不使用预设，配置引擎声音</option>
          {recipeId && !selectedRecipe && <option value={recipeId}>{draftRecipe?.name ?? '原预设'}（不可用）</option>}
          {previewId && previewId !== recipeId && !previewRecipe && <option value={previewId}>待应用预设（已不可用）</option>}
          {compatibleRules.map(item => <option key={item.id} value={item.id}>{item.name} · r{item.revision}</option>)}
        </select></Field>
        {!recipeId && modes.length > 1 && <Field label="声音来源"><select value={engine?.mode ?? ''} onChange={event => {
          const next = modes.find(item => item.id === event.target.value)
          if (next) edit({ mode: next.id, value: next.voice_sources?.default ?? '' })
        }}>{modes.map(item => <option key={item.id} value={item.id}>{modeNames[item.id] || item.id}</option>)}</select></Field>}
        {!recipeId && provider?.connection_required && <Field label="语音服务连接"><select value={engine?.connectionRef ?? ''} onChange={event => edit({ connectionRef: event.target.value })}>
          <option value="">选择已保存的服务连接</option>{matchingConnections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></Field>}
        {!recipeId && catalog && mode?.id !== 'default' && <Field label={modeNames[mode?.id ?? ''] || '声音来源'}>
          {mode?.id === 'reference' ? <select value={engine?.value ?? ''} onChange={event => edit({ value: event.target.value })}>
            <option value="">选择参考录音</option>{assets.map(item => <option key={item.id} value={item.id}>{item.name || item.transcript || item.id}</option>)}
          </select> : catalog.presets.length && catalog.allow_custom ? <>
            <input list={presetListId} value={engine?.value ?? ''} placeholder="选择预设或填写已知音色 ID" onChange={event => edit({ value: event.target.value })} />
            <datalist id={presetListId}>{catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</datalist>
          </> : catalog.presets.length ? <select value={engine?.value ?? ''} onChange={event => edit({ value: event.target.value })}>
            {engine && !catalog.presets.some(item => item.id === engine.value) && <option value={engine.value}>{engine.value || '选择预设声音'}（自定义 ID）</option>}
            {catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}{item.language ? ` · ${item.language}` : ''}</option>)}
          </select> : mode?.id === 'design' ? <textarea rows={2} value={engine?.value ?? ''} placeholder={catalog.description} onChange={event => edit({ value: event.target.value })} />
            : <input value={engine?.value ?? ''} placeholder={catalog.description} onChange={event => edit({ value: event.target.value })} />}
        </Field>}
        {!recipeId && provider?.provider_id === 'fish_audio' && mode?.id === 'hosted' && <FishVoicePicker
          key={engine?.connectionRef || ''} connectionId={engine?.connectionRef || ''}
          value={engine?.value || ''} onSelect={value => edit({ value })} />}
      </div>
      {previewId !== null && <section className="workbench-speech-preview" aria-label="TTS 高级预设预览">
        <h4>{previewRecipe ? `${previewRecipe.name} · r${previewRecipe.revision}` : previewId ? '预设不可用' : '直接配置引擎声音'}</h4>
        {previewRecipe && <>
          <p>来源：我的音色 · {previewRecipe.provider_id} / {previewRecipe.model} · {modeNames[previewRecipe.mode] || previewRecipe.mode}</p>
          <p>声音来源：{previewRecipe.variant.kind === 'reference' ? assets.find(item => item.id === previewRecipe.variant.value)?.name || previewRecipe.variant.value : previewRecipe.variant.value || '引擎默认声音'} · 语言：{previewRecipe.language || '跟随目标语言'}</p>
          <p>运行连接：{connections.find(item => item.id === previewRecipe.connection_ref)?.name || previewRecipe.connection_ref || '无需外部连接'}</p>
          <pre aria-label="预设合成参数">{JSON.stringify({ ...previewRecipe.provider_options,
            ...(previewRecipe.default_delivery ? { default_delivery: previewRecipe.default_delivery } : {}),
            ...(previewRecipe.default_emotion ? { default_emotion: previewRecipe.default_emotion } : {}),
            ...(previewRecipe.default_pause_ms !== undefined ? { default_pause_ms: previewRecipe.default_pause_ms } : {}),
          }, null, 2)}</pre>
        </>}
        <p>{previewId ? '应用将替换 TTS 的声音来源、运行连接与合成参数。' : '解除预设引用，保留可编辑的声音来源与引擎参数；预设的默认表现、情绪和停顿不再沿用。'}保留流程步骤、产出、输入素材和目标语言，不启动任务。</p>
        {previewIssue && <p role="alert" className="workbench-speech-error">{previewIssue}</p>}
        <div className="workbench-speech-actions"><button type="button" disabled={!!previewIssue || !engine} onClick={applyPreview}>应用 TTS 高级预设</button><button type="button" onClick={() => setPreviewId(null)}>取消预览</button></div>
      </section>}
      {applyNotice && <p role="status" className="workbench-speech-muted">{applyNotice}</p>}
      {legacyDevice && <p className="workbench-speech-muted">旧设备设置（{legacyDevice}）由执行层保留；若改为直接配置，请在连接管理中设置设备。</p>}
      {!recipeId && engine?.providerOptions.device !== undefined && <p className="workbench-speech-muted">设备需在连接管理中设置，请移除当前引擎参数中的 device。</p>}
      {!recipeId && catalog?.description && <p className="workbench-speech-muted">{catalog.description}</p>}
      {selectedRecipe && <div className="workbench-speech-actions"><span className="workbench-speech-muted">已应用：{draftRecipe?.name || selectedRecipe.name} · r{draftRecipe?.revision ?? selectedRecipe.revision}。仅用于 TTS；目标语言仍为 {language}。</span><button type="button" onClick={() => { setPreviewId(selectedRecipe.id); setApplyNotice('') }}>查看当前预设</button></div>}
      {!recipeId && provider && engine && <details><summary>TTS 高级参数</summary>
        <SpeechOptionsFields provider={provider} mode={engine.mode} model={engine.model} values={engine.providerOptions} onChange={providerOptions => edit({ providerOptions })} />
      </details>}
      <div className="workbench-speech-actions">
        <button type="button" onClick={() => setPage('voice-lab')}>管理录音与 TTS 高级预设</button>
        {provider?.connection_required && <button type="button" onClick={() => openEngines('external')}>管理外部服务</button>}
      </div>
    </fieldset>
    <div className="workbench-speech-actions"><button type="button" disabled={disabled || loading} onClick={() => setReload(value => value + 1)}>{loading ? '正在加载…' : '刷新引擎与声音'}</button></div>
    {libraryError && <p role="status" className="workbench-speech-muted">{libraryError}</p>}
    {resolution.error && !loading && <p role="status" className="workbench-speech-error">{resolution.error}</p>}
  </div>
}
