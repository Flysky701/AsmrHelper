import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { capabilitiesApi } from '@/api/capabilities'
import { settingsApi } from '@/api/settings'
import type { SettingsView } from '@/api/settings'
import { speechApi } from '@/api/speech'
import type { Delivery, ReferenceAsset, SpeechConnection, SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { CapabilityDescriptorResponse, CapabilityOptionResponse } from '@/api/types'
import type { GraphLanguage, GraphNode } from '@/domain/workflowGraph'
import { copyRecipeToGraphNode, editableGraphOptions, freshGraphSpeechNode, graphNodeFromRecipe,
  graphSpeechIssue, readGraphSpeechSource, setGraphOption, unknownGraphOptions, withGraphSpeechSource } from '@/domain/graphNodeParameters'
import type { GraphSpeechSource } from '@/domain/graphNodeParameters'
import { speechLanguageMatches } from '@/domain/speechAdvancedOptions'
import SpeechOptionsFields from '../SpeechOptionsFields'
import './GraphNodeParameters.css'

interface Props { node: GraphNode; onChange: (node: GraphNode) => void; disabled?: boolean }
const languageNames: Record<GraphLanguage, string> = { zh: '中文', ja: '日语', en: '英语' }
const modeNames: Record<string, string> = { default: '引擎默认声音', builtin: '预设声音', hosted: '服务端音色', reference: '参考录音克隆', design: '声音描述' }
const deliveryNames = { normal: '自然', soft: '轻柔', whisper: '耳语' }
const emotionNames: Record<string, string> = { neutral: '自然', happy: '开心', sad: '悲伤', angry: '愤怒', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const optionNames: Record<string, string> = { beam_size: '搜索宽度', batch_size: '批量大小', temperature: '采样温度', top_p: '采样范围', initial_prompt: '识别提示词', vad_filter: '语音活动过滤', condition_on_previous_text: '参考前文', word_timestamps: '词级时间戳', max_tokens: '最大输出长度', timeout: '超时（秒）' }
function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="graph-param-field"><span>{label}</span>{children}</label>
}
function Language({ node, field, onChange }: Props & { field: 'source_lang' | 'target_lang' }) {
  return <Field label={field === 'source_lang' ? '输入语言' : '目标语言'}><select value={node[field] ?? ''}
    onChange={event => onChange({ ...node, [field]: event.target.value || null })}>
    <option value="">选择语言</option>{Object.entries(languageNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
  </select></Field>
}

/** Keying the local metadata panel prevents a late response or pending confirmation crossing nodes. */
export default function GraphNodeParameters(props: Props) {
  return <NodeParameters key={`${props.node.id}:${props.node.kind}`} {...props} />
}

function NodeParameters({ node, onChange, disabled = false }: Props) {
  const [pending, setPending] = useState<{ description: string; node: GraphNode } | null>(null)
  const requestChange = (next: GraphNode, description: string) => setPending({ node: next, description })
  const scopedChange = (next: GraphNode) => { setPending(null); onChange(next) }
  return <div className="graph-node-parameters" data-node-id={node.id}>
    <fieldset disabled={disabled}>
      <legend className="graph-param-legend">节点 {node.id} 的运行参数</legend>
      <div className="graph-param-grid">
        {['asr', 'align', 'translate'].includes(node.kind) && <Language node={node} field="source_lang" onChange={scopedChange} />}
        {['translate', 'tts'].includes(node.kind) && <Language node={node} field="target_lang" onChange={scopedChange} />}
      </div>
      {['asr', 'translate', 'separate'].includes(node.kind)
        && <CapabilityParameters node={node} onChange={scopedChange} requestChange={requestChange} />}
      {node.kind === 'tts' && <SpeechParameters node={node} onChange={scopedChange} requestChange={requestChange} />}
      {node.kind === 'align' && <p className="graph-param-note">使用 Qwen3 Forced Aligner 0.6B；需要匹配的音频与字幕，不会自动补跑识别。</p>}
      {node.kind === 'mix' && <>
        <div className="graph-param-grid">{([['original_volume', '音频轨音量', 0.85], ['tts_volume_ratio', '配音轨音量', 0.5], ['tts_delay_ms', '配音延迟（毫秒）', 0]] as const).map(([key, label, fallback]) =>
          <Field key={key} label={label}><input type="number" min={0} step={key === 'tts_delay_ms' ? 1 : 0.1} value={String(node.options[key] ?? fallback)}
            onChange={event => scopedChange(setGraphOption(node, 'options', key, event.target.value === '' ? undefined : Number(event.target.value)))} /></Field>)}</div>
        <p className="graph-param-note">两路音频需确认对应同一时间轴。延迟后超出底轨或裁切配音时会拒绝运行。</p>
      </>}
      {node.kind === 'export' && <Field label="字幕格式"><select value={String(node.options.subtitle_format ?? 'srt')}
        onChange={event => scopedChange(setGraphOption(node, 'options', 'subtitle_format', event.target.value))}>
        {['srt', 'vtt', 'lrc'].map(format => <option key={format} value={format}>{format.toUpperCase()}</option>)}
      </select></Field>}
      {pending && <section className="graph-param-confirm" aria-label="确认节点参数变更">
        <p>{pending.description} 只修改当前节点；不修改其他节点、连线、素材或已保存的 TTS 预设。</p>
        <div className="graph-param-actions"><button type="button" onClick={() => { onChange(pending.node); setPending(null) }}>确认更换</button>
          <button type="button" onClick={() => setPending(null)}>取消</button></div>
      </section>}
    </fieldset>
  </div>
}

interface EditorProps extends Props { requestChange: (node: GraphNode, description: string) => void }
function CapabilityParameters({ node, onChange, requestChange }: EditorProps) {
  const [descriptors, setDescriptors] = useState<CapabilityDescriptorResponse[]>([])
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const category = node.kind === 'translate' ? 'llm' : node.kind === 'separate' ? 'separator' : 'asr'
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([capabilitiesApi.list(category), category === 'llm' ? settingsApi.get() : Promise.resolve(null)])
      .then(([items, config]) => { if (active) { setDescriptors(items); setSettings(config?.settings ?? null) } })
      .catch(() => { if (active) { setError('能力或连接信息加载失败，请重试；尚未检查引擎运行环境。'); setDescriptors([]); setSettings(null) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [category, revision])
  const descriptor = descriptors.find(item => item.provider === node.provider)
  const unknown = descriptor && ['asr', 'translate'].includes(node.kind) ? unknownGraphOptions(node, descriptor) : []
  const connectionRef = typeof node.options.connection_ref === 'string' ? node.options.connection_ref : ''
  const connections = settings?.connection_profiles.llm ?? []
  const selectedConnection = connections.find(item => item.id === connectionRef)
  const defaultConnection = connections.find(item => item.id === settings?.connection_profiles.active_llm)
  const changeProvider = (provider: string) => {
    const next = descriptors.find(item => item.provider === provider)
    if (next && provider !== node.provider) requestChange({ ...node, provider, model: next.default_model, options: node.kind === 'separate' ? { mode: 'vocals' } : {}, provider_options: {} }, '更换引擎将重置此节点的模型、连接引用及不兼容参数。')
  }
  return <div className="graph-param-section">
    {loading && <p role="status">正在读取节点能力…</p>}
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={loading || !!error}>
      <div className="graph-param-grid">
        <Field label="引擎"><select value={node.provider} disabled={node.kind === 'separate'} onChange={event => changeProvider(event.target.value)}>
          {!descriptor && <option value={node.provider}>{node.provider || '选择引擎'}（待确认）</option>}
          {descriptors.map(item => <option key={item.provider} value={item.provider}>{item.display_name}</option>)}
        </select></Field>
        <Field label="模型"><input list={`graph-model-${node.id}`} value={node.model ?? ''} placeholder={selectedConnection?.model || descriptor?.default_model || '使用已配置默认模型'}
          onChange={event => onChange({ ...node, model: event.target.value || null })} />
          <datalist id={`graph-model-${node.id}`}>{descriptor?.supported_models.map(model => <option key={model} value={model} />)}</datalist>
        </Field>
      </div>
      {node.kind === 'translate' && <>
        <Field label="翻译服务连接"><select value={connectionRef} onChange={event => {
          const connection = connections.find(item => item.id === event.target.value)
          if (connection && connection.provider !== node.provider) requestChange({ ...node, provider: connection.provider, model: connection.model || null, options: { connection_ref: connection.id }, provider_options: {} }, '此连接使用另一引擎，将重置此节点模型和引擎参数。')
          else onChange(setGraphOption(node, 'options', 'connection_ref', event.target.value || undefined))
        }}>
          <option value="">选择已保存连接</option>
          {connectionRef && !connections.some(item => item.id === connectionRef) && <option value={connectionRef}>{connectionRef}（已不可用）</option>}
          {connections.map(item => <option key={item.id} value={item.id}>{item.name} · {item.provider}</option>)}
        </select></Field>
        <p className="graph-param-note">{selectedConnection
          ? `所选连接：${selectedConnection.name} · ${selectedConnection.provider} · ${selectedConnection.model || '模型未设定'}；${selectedConnection.credential_configured ? '已配置凭据' : '尚未配置凭据'}。`
          : '此节点尚未绑定有效连接，请选择已保存连接。'}未进行连接测试。</p>
        {defaultConnection && <div className="graph-param-actions"><span className="graph-param-note">设置中的默认连接：{defaultConnection.name} · {defaultConnection.model || '模型未设定'}</span>
          <button type="button" onClick={() => requestChange({ ...node, provider: defaultConnection.provider, model: defaultConnection.model || null,
            options: { ...(node.provider === defaultConnection.provider ? node.options : {}), connection_ref: defaultConnection.id },
            provider_options: node.provider === defaultConnection.provider ? { ...node.provider_options } : {} }, '使用设置中的当前默认连接和模型；若引擎不同，将重置不兼容参数。')}>使用当前默认连接和模型</button></div>}
        {selectedConnection && selectedConnection.provider !== node.provider && <p role="alert">连接的引擎与当前节点不一致，请显式选择匹配的连接。</p>}
      </>}
      {node.kind === 'separate' && <p className="graph-param-note">当前只输出人声轨，不提供背景轨。模型采用当前分离能力声明的名称。</p>}
      {descriptor && ['asr', 'translate'].includes(node.kind) && <details><summary>引擎参数</summary>
        {(['options', 'provider_options'] as const).map(scope => <div className="graph-param-grid" key={scope}>
          {editableGraphOptions(scope === 'options' ? descriptor.common_option_schema : descriptor.provider_option_schema).map(field =>
            <CapabilityField key={field.name} field={field} value={node[scope][field.name]} onChange={value => onChange(setGraphOption(node, scope, field.name, value))} />)}
        </div>)}
      </details>}
      {unknown.length > 0 && <div role="alert"><p>已有参数不在此编辑器支持范围：{unknown.join('、')}。未静默删除；运行仍需通过后端校验。</p>
        <button type="button" onClick={() => requestChange({ ...node,
          options: Object.fromEntries(Object.entries(node.options).filter(([key]) => !unknown.includes(`options.${key}`))),
          provider_options: Object.fromEntries(Object.entries(node.provider_options).filter(([key]) => !unknown.includes(`provider_options.${key}`))) }, '移除显示的不支持参数。')}>移除这些参数</button></div>}
    </fieldset>
    <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新能力信息</button>
  </div>
}

function CapabilityField({ field, value, onChange }: { field: CapabilityOptionResponse; value: unknown; onChange: (value: unknown) => void }) {
  const current = value ?? field.default
  const id = useId()
  return <div className="graph-param-field"><label htmlFor={id}>{optionNames[field.name] || field.name}{field.required ? '（必填）' : ''}</label>
    {field.type === 'boolean' ? <input id={id} type="checkbox" checked={current === true} onChange={event => onChange(event.target.checked)} />
      : field.enum.length ? <select id={id} value={String(current ?? '')} onChange={event => onChange(field.enum.find(item => String(item) === event.target.value))}>
        <option value="">引擎默认</option>{field.enum.map(item => <option key={String(item)} value={String(item)}>{String(item)}</option>)}
      </select> : <input id={id} type={['number', 'integer'].includes(field.type) ? 'number' : 'text'} value={String(current ?? '')}
        min={field.min ?? undefined} max={field.max ?? undefined} step={field.type === 'integer' ? 1 : 'any'}
        onChange={event => onChange(event.target.value === '' ? undefined : ['number', 'integer'].includes(field.type) ? Number(event.target.value) : event.target.value)} />}
    {field.description && <small>{field.description}</small>}
  </div>
}

function SpeechParameters({ node, onChange, requestChange }: EditorProps) {
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [recipes, setRecipes] = useState<SpeechRecipe[]>([])
  const [assets, setAssets] = useState<ReferenceAsset[]>([])
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [previewId, setPreviewId] = useState('')
  const [copyError, setCopyError] = useState('')
  const voiceList = useId()
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([speechApi.providers(), speechApi.rules(), speechApi.references(), speechApi.connections()])
      .then(([catalog, rules, references, connectionList]) => {
        if (!active) return
        setProviders(catalog.providers); setRecipes(rules.recipes.filter(item => !item.archived))
        setAssets(references.assets.filter(item => !item.archived)); setConnections(connectionList.connections)
      }).catch(() => { if (active) setError('声音能力、已保存预设或素材读取失败，请重试。当前节点设置仍保留。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])
  const provider = providers.find(item => item.provider_id === node.provider)
  const source = readGraphSpeechSource(node)
  const selected = recipes.find(item => item.id === node.options.speech_recipe_id)
  const preview = recipes.find(item => item.id === previewId)
  const models = [...new Set(provider?.modes.flatMap(item => item.models) ?? [])]
  const modes = provider?.modes.filter(item => !item.models.length || item.models.includes(node.model ?? '')) ?? []
  const mode = modes.find(item => item.id === source?.mode)
  const catalog = mode?.voice_sources
  const matchingConnections = connections.filter(item => item.provider_id === node.provider)
  const selectedConnection = matchingConnections.find(item => item.id === source?.connection_ref)
  const reference = source?.variant.kind === 'reference' ? assets.find(item => item.id === source.variant.value) : undefined
  const issue = loading || error ? '' : graphSpeechIssue(node, provider, recipes, assets, connections)
  const updateSource = (patch: Partial<GraphSpeechSource>) => { if (source) onChange(withGraphSpeechSource(node, { ...source, ...patch })) }
  const changeValue = (value: string) => { if (source) updateSource({ variant: { ...source.variant, value } }) }
  const capabilities = mode?.capabilities ?? provider?.capabilities
  const deliveryCaps = capabilities?.delivery as Record<string, { support?: string }> | undefined
  const emotionCaps = capabilities?.emotion as { support?: string } | undefined
  return <div className="graph-param-section">
    {loading && <p role="status">正在读取语音能力和已保存素材…</p>}
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={loading || !!error}>
      <Field label="TTS 高级预设"><select value={previewId} onChange={event => { setPreviewId(event.target.value); setCopyError('') }}>
        <option value="">选择已保存预设，预览后应用</option>{recipes.map(item => <option key={item.id} value={item.id}>{item.name} · r{item.revision} · {item.provider_id}</option>)}
      </select></Field>
      {preview && <section className="graph-param-confirm" aria-label="配音预设应用预览">
        <p>{preview.name} · {preview.provider_id} / {preview.model} · {modeNames[preview.mode] || preview.mode} · {preview.language || '自动语言'}</p>
        <p>应用将替换此节点的声音来源、连接和合成参数，目标语言仍为 {languageNames[node.target_lang ?? 'zh']}。</p>
        {!speechLanguageMatches(preview.language, node.target_lang ?? '') && <p role="alert">预设语言与此节点目标语言不一致，请更换预设或自行调整目标语言。</p>}
        <div className="graph-param-actions"><button type="button" disabled={!speechLanguageMatches(preview.language, node.target_lang ?? '')}
          onClick={() => { onChange(graphNodeFromRecipe(node, preview)); setPreviewId('') }}>应用到此节点</button><button type="button" onClick={() => setPreviewId('')}>取消预览</button></div>
      </section>}
      {node.options.speech_recipe_id ? <section className="graph-param-confirm">
        <p>已引用：{selected ? `${selected.name} · r${selected.revision}` : String(node.options.speech_recipe_id)}。提交时冻结对应修订，不修改原预设。</p>
        {selected && <>
          <p>默认演绎：{deliveryNames[selected.default_delivery ?? 'normal']} · {emotionNames[selected.default_emotion ?? 'neutral'] ?? selected.default_emotion} · 停顿 {selected.default_pause_ms ?? 0} 毫秒</p>
          <button type="button" onClick={() => { try { onChange(copyRecipeToGraphNode(node, selected)); setCopyError('') } catch (cause) { setCopyError(String(cause instanceof Error ? cause.message : cause)) } }}>复制为本节点参数并编辑</button>
        </>}
        {copyError && <p role="alert">{copyError}</p>}
      </section> : null}
      <div className="graph-param-grid">
        <Field label="配音引擎"><select value={node.provider} onChange={event => {
          const next = providers.find(item => item.provider_id === event.target.value)
          if (next && node.provider !== next.provider_id) requestChange(freshGraphSpeechNode(node, next), '更换配音引擎将重置模型、来源、预设引用和高级参数。')
        }}>
          {!provider && <option value={node.provider}>{node.provider || '选择引擎'}（待确认）</option>}
          {providers.map(item => <option key={item.provider_id} value={item.provider_id}>{item.name}</option>)}
        </select></Field>
        <Field label="配音模型">{models.length ? <select value={node.model ?? ''} onChange={event => {
          if (provider && event.target.value !== node.model) requestChange(freshGraphSpeechNode(node, provider, event.target.value), '更换配音模型将重置声音来源、预设引用和高级参数。')
        }}>
          {!models.includes(node.model ?? '') && <option value={node.model ?? ''}>{node.model || '选择模型'}（待确认）</option>}
          {models.map(model => <option key={model} value={model}>{model}</option>)}
        </select> : <input value={node.model ?? ''} placeholder="服务文档中的模型 ID" disabled={!!node.options.speech_recipe_id}
          onChange={event => onChange({ ...node, model: event.target.value || null })} />}</Field>
      </div>
      {!node.options.speech_recipe_id && !source && provider && <button type="button" onClick={() => requestChange(freshGraphSpeechNode(node, provider, node.model && node.model !== 'default' ? node.model : undefined), '配置该引擎的明确声音来源将替换此节点已有简写声音参数。')}>配置声音来源</button>}
      {!node.options.speech_recipe_id && source && <>
        <Field label="声音来源"><select value={source.mode} onChange={event => {
          if (provider && event.target.value !== source.mode) requestChange(freshGraphSpeechNode(node, provider, node.model ?? undefined, event.target.value), '更换声音模式将重置来源、高级参数和默认演绎；运行连接保留。')
        }}>
          {!mode && <option value={source.mode}>{source.mode}（待确认）</option>}
          {modes.map(item => <option key={item.id} value={item.id}>{modeNames[item.id] || item.id}</option>)}
        </select></Field>
        <Field label="语音服务连接"><select value={source.connection_ref ?? ''} onChange={event => updateSource({ connection_ref: event.target.value || undefined })}>
          <option value="">{provider?.connection_required ? '选择已保存连接' : '使用引擎默认连接'}</option>
          {source.connection_ref && !selectedConnection && <option value={source.connection_ref}>{source.connection_ref}（待确认）</option>}
          {matchingConnections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></Field>
        <p className="graph-param-note">{selectedConnection ? `连接：${selectedConnection.name} · ${selectedConnection.deployment}`
          : provider?.connection_required ? '当前未选择可用的外部连接' : '使用引擎默认运行配置'}。就绪状态尚未检查，不代表可以立即合成。</p>
        {catalog && source.mode !== 'default' && <Field label={modeNames[source.mode] || '声音来源'}>
          {source.variant.kind === 'reference' ? <select value={source.variant.value} onChange={event => changeValue(event.target.value)}>
            <option value="">选择已保存参考录音</option>
            {source.variant.value && !reference && <option value={source.variant.value}>原参考录音（不可用）</option>}
            {assets.map(item => <option key={item.id} value={item.id}>{item.name || item.id} · {item.language || '语言未知'}</option>)}
          </select> : catalog.presets.length && !catalog.allow_custom ? <select value={source.variant.value} onChange={event => changeValue(event.target.value)}>
            {!catalog.presets.some(item => item.id === source.variant.value) && <option value={source.variant.value}>{source.variant.value || '选择声音'}</option>}
            {catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
          </select> : source.mode === 'design' ? <textarea value={source.variant.value} rows={3} onChange={event => changeValue(event.target.value)} />
            : <><input list={voiceList} value={source.variant.value} onChange={event => changeValue(event.target.value)} placeholder={catalog.description} />
              <datalist id={voiceList}>{catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</datalist></>}
        </Field>}
        {catalog?.description && <p className="graph-param-note">{catalog.description}</p>}
        {reference && <div className="graph-param-reference"><p>{reference.name || reference.id} · {reference.language || '语言未知'} · {reference.confirmed ? '原文已核对' : '原文未确认'}</p>
          <audio controls preload="none" src={speechApi.referenceAudio(reference.id)} aria-label="试听所选参考录音" />
          <p>{reference.transcript || '无参考原文'}</p></div>}
        {provider && <details><summary>TTS 高级参数</summary>
          <SpeechOptionsFields provider={provider} mode={source.mode} model={node.model ?? ''} values={source.provider_options} onChange={provider_options => updateSource({ provider_options })} />
          <div className="graph-param-grid">
            <Field label="默认演绎"><select value={source.default_delivery ?? 'normal'} onChange={event => updateSource({ default_delivery: event.target.value as Delivery })}>
              {Object.entries(deliveryNames).filter(([value]) => value === 'normal' || deliveryCaps?.[value]?.support === 'direct' || value === source.variant.style || value === source.default_delivery)
                .map(([value, label]) => <option key={value} value={value} disabled={value !== 'normal' && deliveryCaps?.[value]?.support !== 'direct' && value !== source.variant.style}>{label}</option>)}
            </select></Field>
            {(emotionCaps?.support === 'direct' || source.default_emotion && source.default_emotion !== 'neutral') && <Field label="默认情绪"><select value={source.default_emotion ?? 'neutral'} onChange={event => updateSource({ default_emotion: event.target.value })}>
              {Object.entries(emotionNames).map(([value, label]) => <option key={value} value={value} disabled={value !== 'neutral' && emotionCaps?.support !== 'direct'}>{label}</option>)}
            </select></Field>}
            <Field label="句后停顿（毫秒）"><input type="number" min={0} max={30000} step={1} value={source.default_pause_ms ?? 0}
              onChange={event => updateSource({ default_pause_ms: event.target.value === '' ? undefined : Number(event.target.value) })} /></Field>
          </div>
          <p className="graph-param-note">仅显示此引擎声明的参数；设备、精度及模型路径在连接中配置。时间轴适配可能调整正式成品的时长。</p>
        </details>}
      </>}
    </fieldset>
    {issue && <p role="alert">{issue}</p>}
    <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新声音与连接</button>
  </div>
}
