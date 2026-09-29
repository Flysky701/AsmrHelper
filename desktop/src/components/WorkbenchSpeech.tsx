import { useEffect, useId, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, SpeechConnection, SpeechProvider, SpeechRecipe, WorkbenchSpeechSource } from '@/api/speech'
import type { StageProfileRequest } from '@/api/types'
import { compatibleSpeechRules, initialSpeechEngine } from '@/domain/workbenchSpeech'
import { useSpeechDraftStore } from '@/stores/speechDraftStore'
import type { SpeechEngineDraft } from '@/stores/speechDraftStore'
import { useNavStore } from '@/stores/navStore'
import './WorkbenchSpeech.css'

export interface WorkbenchSpeechResolution {
  stage: StageProfileRequest | null
  error: string
  summary: string
  recipe?: SpeechRecipe
}
const modeNames: Record<string, string> = { default: '引擎默认声音', builtin: '预设声音', hosted: '服务端音色', reference: '参考录音克隆', design: '声音描述' }
const optionNames: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围', device: '运算设备', cfg_value: '引导强度', inference_timesteps: '推理步数', style_description: '风格描述', tag_density: '标签密度' }
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="workbench-speech-field"><span>{label}</span>{children}</label>
}

export default function WorkbenchSpeech({ disabled, language, preferredProvider, onChange }: {
  disabled: boolean
  language: string
  preferredProvider: string
  onChange: (resolution: WorkbenchSpeechResolution) => void
}) {
  const { engine, recipeId, recipe: draftRecipe, setEngine, setRecipe, clear } = useSpeechDraftStore()
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
  const options = Object.entries(provider?.options_schema.properties ?? {}).filter(([key, rule]) => key !== 'schema_version' && rule.const === undefined)

  const resolution = useMemo<WorkbenchSpeechResolution>(() => {
    const invalid = (error: string): WorkbenchSpeechResolution => ({ stage: null, error, summary: provider?.name ?? '待选择引擎' })
    if (loading) return invalid('正在加载配音能力…')
    if (catalogError) return invalid(catalogError)
    if (!engine || !provider) return invalid('请选择可用的配音引擎')
    if (!engine.model.trim()) return invalid('请根据服务文档填写模型 ID')
    if (recipeId) {
      if (!selectedRecipe) return invalid('原自定义规则已不可用或与当前引擎、模型不兼容，请重新选择或使用引擎声音')
      return {
        stage: { enabled: true, provider: provider.provider_id, model: engine.model,
          options: { speech_recipe_id: selectedRecipe.id }, provider_options: {} },
        error: '', summary: `${provider.name} · ${selectedRecipe.name} · r${selectedRecipe.revision}`, recipe: selectedRecipe,
      }
    }
    if (!mode || !mode.voice_sources) return invalid('当前引擎未提供声音来源能力，请刷新或选择其他模型')
    if (provider.connection_required && !matchingConnections.some(item => item.id === engine.connectionRef)) return invalid('请选择与当前引擎匹配的外部服务连接')
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
  }, [engine, provider, mode, loading, catalogError, recipeId, selectedRecipe, language, assets, connections])

  useEffect(() => { onChange(resolution) }, [resolution, onChange])

  const edit = (patch: Partial<SpeechEngineDraft>) => { if (engine) setEngine({ ...engine, ...patch }) }
  const changeModel = (model: string) => {
    if (!provider || !engine) return
    const next = initialSpeechEngine(provider, model)
    setEngine({ ...next, connectionRef: engine.connectionRef })
  }

  return <div className="workbench-speech">
    <fieldset disabled={disabled || loading}>
      <div className="workbench-speech-grid">
        <Field label="配音引擎"><select value={engine?.providerId ?? ''} onChange={event => {
          const next = providers.find(item => item.provider_id === event.target.value)
          if (next) setEngine(initialSpeechEngine(next))
        }}><option value="">选择引擎</option>{providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
          {engine && !provider && <option value={engine.providerId}>{engine.providerId}（暂不可用）</option>}
        </select></Field>
        <Field label={models.length ? '配音模型' : '模型 ID'}>{models.length ? <select value={engine?.model ?? ''} onChange={event => changeModel(event.target.value)}>
          {engine && !models.includes(engine.model) && <option value={engine.model}>{engine.model || '选择模型'}（待确认）</option>}
          {models.map(model => <option key={model} value={model}>{model}</option>)}
        </select> : <input value={engine?.model ?? ''} placeholder="填写服务文档中的模型 ID" onChange={event => changeModel(event.target.value)} />}</Field>
        <Field label="自定义规则（可选）"><select value={recipeId ?? ''} onChange={event => {
          const next = compatibleRules.find(item => item.id === event.target.value)
          if (next) setRecipe(next)
          else if (provider && engine) setEngine({ ...initialSpeechEngine(provider, engine.model), connectionRef: engine.connectionRef })
          else clear()
        }}><option value="">不使用规则，配置引擎声音</option>
          {recipeId && !selectedRecipe && <option value={recipeId}>{draftRecipe?.name ?? '原规则'}（不可用）</option>}
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
      </div>
      {!recipeId && catalog?.description && <p className="workbench-speech-muted">{catalog.description}</p>}
      {selectedRecipe && <p className="workbench-speech-muted">使用已保存规则的声音、语言和参数；提交时固定当前修订。</p>}
      {!recipeId && options.length > 0 && <details><summary>引擎参数</summary><div className="workbench-speech-grid">
        {options.map(([key, schema]) => <Field key={key} label={schema.title || optionNames[key] || key}>
          {schema.enum ? <select value={String(engine?.providerOptions[key] ?? schema.default ?? '')} onChange={event => edit({ providerOptions: { ...engine?.providerOptions, [key]: schema.type === 'number' || schema.type === 'integer' ? Number(event.target.value) : event.target.value } })}>
            {schema.enum.map(value => <option key={String(value)} value={String(value)}>{String(value)}</option>)}
          </select> : <input type={schema.type === 'number' || schema.type === 'integer' ? 'number' : 'text'}
            min={schema.minimum} max={schema.maximum} step={schema.type === 'integer' ? 1 : 'any'}
            value={String(engine?.providerOptions[key] ?? schema.default ?? '')} onChange={event => edit({ providerOptions: { ...engine?.providerOptions, [key]: schema.type === 'number' || schema.type === 'integer' ? Number(event.target.value) : event.target.value } })} />}
        </Field>)}
      </div></details>}
      <div className="workbench-speech-actions">
        <button type="button" onClick={() => setPage('voice-lab')}>管理参考录音与规则</button>
        {provider?.connection_required && <button type="button" onClick={() => openEngines('external')}>管理外部服务</button>}
      </div>
    </fieldset>
    <div className="workbench-speech-actions"><button type="button" disabled={disabled || loading} onClick={() => setReload(value => value + 1)}>{loading ? '正在加载…' : '刷新引擎与声音'}</button></div>
    {libraryError && <p role="status" className="workbench-speech-muted">{libraryError}</p>}
    {resolution.error && !loading && <p role="status" className="workbench-speech-error">{resolution.error}</p>}
  </div>
}
