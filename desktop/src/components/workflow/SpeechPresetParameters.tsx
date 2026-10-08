import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { Delivery, OptionSchema, SpeechConnection, SpeechLibrary, SpeechOverrides, SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { GraphNode } from '@/domain/workflowGraph'
import { graphNodeFromRecipe, graphSpeechIssue, graphSpeechOptionDisabledReason } from '@/domain/graphNodeParameters'
import type { GraphParameterSection } from '@/domain/graphNodeParameters'
import { effectiveSpeechRecipe, runtimeSpeechOptions, speechOverrideIssue, withSpeechOverrides } from '@/domain/speechPresetConsumption'
import { speechLanguageMatches } from '@/domain/speechAdvancedOptions'
import { openSpeechPresetLibrary } from '@/stores/speechPresetHandoffStore'

const deliveryNames: Record<string, string> = { normal: '自然', soft: '轻柔', whisper: '耳语' }
const emotionNames: Record<string, string> = { neutral: '自然', happy: '开心', sad: '悲伤', angry: '愤怒', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const optionNames: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围', style_description: '演绎描述', tag_density: '标签密度', cfg_value: '引导强度', inference_timesteps: '推理步数' }
const languages: Record<string, string> = { zh: '中文', ja: '日语', en: '英语' }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="graph-param-field"><span>{label}</span>{children}</label> }

export default function SpeechPresetParameters({ node, onChange, requestChange, section = 'all' }: {
  node: GraphNode; onChange: (node: GraphNode) => void; requestChange: (node: GraphNode, description: string) => void; section?: GraphParameterSection
}) {
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [recipes, setRecipes] = useState<SpeechRecipe[]>([])
  const [library, setLibrary] = useState<SpeechLibrary | null>(null)
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [loading, setLoading] = useState(true), [error, setError] = useState(''), [revision, setRevision] = useState(0)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([speechApi.providers(), speechApi.rules(), speechApi.library(), speechApi.connections()])
      .then(([catalog, rules, saved, links]) => {
        if (!active) return
        setProviders(catalog.providers); setRecipes(rules.recipes.filter(item => !item.archived)); setLibrary(saved); setConnections(links.connections)
      }).catch(() => { if (active) setError('音色库读取失败，节点配置已保留。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])
  useEffect(() => { setNotice('') }, [node.id, node.options.speech_recipe_id])
  const common = section !== 'advanced'
  const selected = library?.recipes.find(item => item.id === node.options.speech_recipe_id)
  const provider = providers.find(item => item.provider_id === node.provider)
  const validIdentity = !!selected && selected.provider_id === node.provider && selected.model === node.model
  const overrideIssue = selected ? speechOverrideIssue(provider, selected, node.options.speech_overrides) : ''
  const overrides = (node.options.speech_overrides ?? {}) as SpeechOverrides
  const effective = selected && !overrideIssue ? effectiveSpeechRecipe(selected, overrides) : selected
  const mode = selected && provider?.modes.find(item => item.id === selected.mode && (!item.models.length || item.models.includes(selected.model)))
  const caps = mode?.capabilities ?? provider?.capabilities
  const delivery = caps?.delivery as Record<string, { support?: string }> | undefined
  const emotion = caps?.emotion as { support?: string } | undefined
  const pause = caps?.pause as { support?: string } | undefined
  const fields = selected && validIdentity ? runtimeSpeechOptions(provider, selected) : []
  const savedRecipes = library?.recipes ?? []
  const issue = !loading && !error ? graphSpeechIssue(node, provider, savedRecipes, library?.assets ?? [], connections) : ''
  const legacy = !node.options.speech_recipe_id && (Object.keys(node.options).length > 0 || Object.keys(node.provider_options).length > 0)
  const retained = Object.keys(node.options).filter(key => !['speech_recipe_id', 'speech_overrides', 'speech_source', 'voice', 'speed', 'language'].includes(key))
  const extraData = retained.length > 0 || Object.keys(node.provider_options).length > 0 || !!node.options.speech_recipe_id && node.options.speech_source !== undefined
  const update = (patch: Partial<SpeechOverrides>) => onChange(withSpeechOverrides(node, { ...overrides, ...patch }))
  const optionsFields = (advanced: boolean) => fields.filter(([key]) => (key !== 'speed') === advanced).map(([key, field]) =>
    <Option key={key} name={key} field={field} value={effective?.provider_options[key]}
      reason={effective ? graphSpeechOptionDisabledReason(node, effective, key) : ''}
      onChange={value => {
        const values = { ...overrides.provider_options }
        if (value === undefined) delete values[key]; else values[key] = value
        update({ provider_options: values })
      }} />)
  const manage = async () => {
    const opened = await openSpeechPresetLibrary(node.options.speech_recipe_id && selected && !extraData && !overrideIssue
      ? { recipeId: selected.id } : { nodeDraft: node })
    if (!opened) setNotice('音色库还有待接入的草稿，或当前操作尚未完成；配置已保留。')
  }
  return <div className="graph-param-section">
    {loading && <p role="status">正在读取音色…</p>}
    {error && <p role="alert">{error}</p>}
    {common && <>
      <Field label="音色"><select disabled={loading || !!error} value={String(node.options.speech_recipe_id ?? '')} onChange={event => {
        const choice = recipes.find(item => item.id === event.target.value)
        if (choice) requestChange(graphNodeFromRecipe(node, choice), `使用“${choice.name}”？本次微调将恢复为该音色的默认值。`)
      }}><option value="" disabled>选择已保存音色</option>
        {!!node.options.speech_recipe_id && !recipes.some(item => item.id === node.options.speech_recipe_id) && <option value={String(node.options.speech_recipe_id)}>{selected?.name || '原音色'}（保留的引用）</option>}
        {recipes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></Field>
      {selected && <p className="graph-param-note">{providers.find(item => item.provider_id === selected.provider_id)?.name || selected.provider_id} · {selected.model}</p>}
      <div className="graph-param-actions"><button type="button" onClick={() => void manage()}>{legacy ? '在音色库另存' : '管理音色'}</button>
        <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新</button></div>
      {legacy && <p className="graph-param-note">旧声音配置已保留，可按原配置运行。编辑声音请先在音色库另存。</p>}
      {!selected && !legacy && !node.options.speech_recipe_id && !loading && <p className="graph-param-note">请先在音色库保存一个音色。</p>}
      <Field label="合成目标语言"><select value={node.target_lang ?? ''} onChange={event => onChange({ ...node, target_lang: event.target.value as GraphNode['target_lang'] })}>
        <option value="" disabled>选择语言</option>{Object.entries(languages).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></Field>
      {selected && !speechLanguageMatches(selected.language, node.target_lang ?? '') && <p role="alert">音色与目标语言不匹配，请选择适合的音色或修改目标语言。</p>}
    </>}
    {selected && validIdentity && mode && <fieldset disabled={loading || !!error || !!overrideIssue} className="graph-param-section">
      {common && <>
        <p className="graph-param-summary">本次微调</p>
        <div className="graph-param-grid">{optionsFields(false)}
          {Object.values(delivery ?? {}).some(item => item.support === 'direct') && Object.values(delivery ?? {}).filter(item => item.support === 'direct').length > 1 && <Field label="演绎"><select value={effective?.default_delivery ?? 'normal'} onChange={event => update({ default_delivery: event.target.value as Delivery })}>
            {Object.entries(deliveryNames).filter(([value]) => delivery?.[value]?.support === 'direct').map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>}
          {emotion?.support === 'direct' && <Field label="情绪"><select value={effective?.default_emotion ?? 'neutral'} onChange={event => update({ default_emotion: event.target.value })}>
            {Object.entries(emotionNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></Field>}
          {pause?.support === 'postprocess' && <Field label="句后停顿（毫秒）"><input type="number" min={0} max={30000} step={1} value={effective?.default_pause_ms ?? 0} onChange={event => update({ default_pause_ms: event.target.value === '' ? undefined : Number(event.target.value) })} /></Field>}
        </div>
      </>}
      {section !== 'common' && (section === 'all' ? <details><summary>更多微调</summary><div className="graph-param-grid">{optionsFields(true)}</div></details> : <div className="graph-param-grid">{optionsFields(true)}</div>)}
    </fieldset>}
    {selected && common && !!node.options.speech_overrides && <button type="button" disabled={loading || !!error} onClick={() => requestChange(withSpeechOverrides(node, {}), '清除本次微调并恢复音色默认值？')}>恢复音色默认值</button>}
    {issue && <p role="alert">{issue}</p>}
    {extraData && <p role="alert">旧配置含未识别参数，已完整保留。请在音色库核对迁移后再运行。</p>}
    {(legacy || extraData || overrideIssue) && common && <details><summary>保留的旧配置</summary><pre>{JSON.stringify({ provider: node.provider, model: node.model, options: node.options, provider_options: node.provider_options }, null, 2)}</pre></details>}
    {notice && <p role="status">{notice}</p>}
    {error && <button type="button" onClick={() => setRevision(value => value + 1)}>重试</button>}
  </div>
}

function Option({ name, field, value, reason, onChange }: { name: string; field: OptionSchema; value: unknown; reason: string; onChange: (value: unknown) => void }) {
  const id = useId(), current = value ?? field.default, numeric = ['number', 'integer'].includes(field.type ?? '')
  return <div className="graph-param-field"><label htmlFor={id}>{field.title || optionNames[name] || name}</label>
    {field.type === 'boolean' ? <input id={id} type="checkbox" checked={current === true} disabled={!!reason} onChange={event => onChange(event.target.checked)} />
      : field.enum ? <select id={id} value={String(current ?? '')} disabled={!!reason} onChange={event => onChange(numeric ? Number(event.target.value) : event.target.value)}>{field.enum.map(item => <option key={String(item)} value={String(item)}>{String(item)}</option>)}</select>
        : <input id={id} type={numeric ? 'number' : 'text'} value={String(current ?? '')} disabled={!!reason} min={field.minimum} max={field.maximum} maxLength={field.maxLength} step={field.type === 'integer' ? 1 : 'any'}
          onChange={event => onChange(event.target.value === '' ? undefined : numeric ? Number(event.target.value) : event.target.value)} />}
    {reason && <small>{reason}</small>}
    {field.description && <details><summary>说明</summary><small>{field.description}</small></details>}
  </div>
}
