import { speechProviderText } from '@/locales/voices'
import { t, useI18n } from '@/i18n'
import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { speechApi } from '@/api/speech'
import type { Delivery, OptionSchema, SpeechConnection, SpeechLibrary, SpeechOverrides, SpeechProvider, SpeechRecipe } from '@/api/speech'
import { GRAPH_OPTION_KEYS, type GraphNode } from '@/domain/workflowGraph'
import { graphNodeFromRecipe, graphSpeechIssue, graphSpeechOptionDisabledReason } from '@/domain/graphNodeParameters'
import { effectiveSpeechRecipe, runtimeSpeechOptions, speechOverrideIssue, withSpeechOverrides } from '@/domain/speechPresetConsumption'
import { speechLanguageMatches, speechCapabilities, speechLanguageSupported } from '@/domain/speechAdvancedOptions'
import { DRAMA3_PROVIDER_ID } from '@/domain/modelDownloads'
import { useNavStore } from '@/stores/navStore'
import { openSpeechPresetLibrary } from '@/stores/speechPresetHandoffStore'
import SpeechProcessingParameters from './SpeechProcessingParameters'

const deliveryNames: Record<string, string> = { normal: '自然', soft: '轻柔', whisper: '耳语' }
const emotionNames: Record<string, string> = { neutral: '自然', happy: '开心', sad: '悲伤', angry: '愤怒', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const optionNames: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围', style_description: '演绎描述', tag_density: '标签密度', cfg_value: '引导强度', inference_timesteps: '推理步数' }
const languages: Record<string, string> = { zh: '中文', ja: '日语', en: '英语' }
function Field({ label, children }: { label: string; children: ReactNode }) {
  useI18n()
  return <label className="graph-param-field"><span>{t(label)}</span>{children}</label> }

export default function SpeechPresetParameters({ node, onChange, requestChange, onSectionChange }: {
  node: GraphNode; onChange: (node: GraphNode) => void
  requestChange: (node: GraphNode, description: string) => void
  onSectionChange: () => void
}) {
  useI18n()
  const [view, setView] = useState<'voice' | 'processing'>('voice')
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
  const selected = library?.recipes.find(item => item.id === node.options.speech_recipe_id)
  const provider = providers.find(item => item.provider_id === node.provider)
  const validIdentity = !!selected && selected.provider_id === node.provider && selected.model === node.model
  const overrideIssue = selected ? speechOverrideIssue(provider, selected, node.options.speech_overrides) : ''
  const overrides = (node.options.speech_overrides ?? {}) as SpeechOverrides
  const effective = selected && !overrideIssue ? effectiveSpeechRecipe(selected, overrides) : selected
  const mode = selected && provider?.modes.find(item => item.id === selected.mode && (!item.models.length || item.models.includes(selected.model)))
  const caps = selected ? speechCapabilities(provider, selected.mode, selected.model) : {}
  const delivery = caps?.delivery as Record<string, { support?: string }> | undefined
  const emotion = caps?.emotion as { support?: string } | undefined
  const pause = caps?.pause as { support?: string } | undefined
  const fields = selected && validIdentity ? runtimeSpeechOptions(provider, selected) : []
  const savedRecipes = library?.recipes ?? []
  const legacyKeys = ['speech_source', 'voice', 'speed', 'language']
  const hasProviderOptions = Object.keys(node.provider_options).length > 0
  const legacy = !node.options.speech_recipe_id && (node.provider !== 'speech' || !!node.model || legacyKeys.some(key => key in node.options) || hasProviderOptions)
  const extraData = Object.keys(node.options).some(key => key !== 'language' && !GRAPH_OPTION_KEYS.tts?.includes(key))
    || hasProviderOptions || !!node.options.speech_recipe_id && node.options.speech_source !== undefined
  const issue = !loading && !error && (legacy || node.options.speech_recipe_id)
    ? graphSpeechIssue(node, provider, savedRecipes, library?.assets ?? [], connections) : ''
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
  const pauseControl = selected && validIdentity && mode && pause?.support === 'postprocess' &&
    <fieldset disabled={loading || !!error || !!overrideIssue}>
      <Field label={t("句后停顿（毫秒）")}><input type="number" min={0} max={30000} step={1} value={effective?.default_pause_ms ?? 0} onChange={event => update({ default_pause_ms: event.target.value === '' ? undefined : Number(event.target.value) })} /></Field>
    </fieldset>

  return <div className="graph-param-section">
    <div className="graph-speech-tabs" role="group" aria-label={t("语音合成设置")}>
      {([['voice', '引擎与声音'], ['processing', '配音处理']] as const).map(([id, name]) =>
        <button type="button" key={id} aria-pressed={view === id} onClick={() => {
          if (view !== id) { setView(id); onSectionChange() }
        }}>{t(name)}</button>)}
    </div>
    {view === 'processing' ? <SpeechProcessingParameters node={node} onChange={onChange} pauseControl={pauseControl} />
      : <div className="graph-param-section">
        {loading && <p role="status">{t("正在读取音色…")}</p>}
        {error && <p role="alert">{t(error)}</p>}
        <Field label={t("音色")}><select disabled={loading || !!error} value={String(node.options.speech_recipe_id ?? '')} onChange={event => {
          const choice = recipes.find(item => item.id === event.target.value)
          if (choice) requestChange(graphNodeFromRecipe(node, choice), `使用“${choice.name}”？本次微调将恢复为该音色的默认值。`)
        }}><option value="" disabled>{t(node.options.auto_clone === true ? "自动克隆原声（失败时用默认音色）" : "选择已保存音色")}</option>
          {!!node.options.speech_recipe_id && !recipes.some(item => item.id === node.options.speech_recipe_id) && <option value={String(node.options.speech_recipe_id)}>{selected?.name || t("原音色")}{t("（保留的引用）")}</option>}
          {recipes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></Field>
        {selected && <p className="graph-param-note">{t(providers.find(item => item.provider_id === selected.provider_id)?.name || selected.provider_id)} · {selected.model}</p>}
        <div className="graph-param-actions"><button type="button" onClick={() => void manage()}>{legacy ? t("在音色库另存") : t("管理音色")}</button>
          {node.provider === DRAMA3_PROVIDER_ID && <button type="button" onClick={() => void useNavStore.getState().openEngines('local', 'tts')}>{t("管理本机 Drama 3 权重")}</button>}
          <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>{t("刷新")}</button></div>
        {legacy && <p className="graph-param-note">{t("编辑旧声音配置，请先在音色库另存。")}</p>}
        {!node.options.auto_clone && !node.options.speech_recipe_id && !legacy && !loading && !error && !recipes.length && <p className="graph-param-note">{t("请先在音色库保存一个音色。")}</p>}
        <Field label={t("合成目标语言")}><select value={node.target_lang ?? ''} onChange={event => onChange({ ...node, target_lang: event.target.value as GraphNode['target_lang'] })}>
          <option value="" disabled>{t("选择语言")}</option>{Object.entries(languages).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
        </select></Field>
        {selected && !speechLanguageSupported(provider, selected.mode, selected.model, node.target_lang ?? '') && <p role="alert">{t('当前模型不支持所选目标语言，请重新选择。')}</p>}
        {selected && !speechLanguageMatches(selected.language, node.target_lang ?? '') && <p role="alert">{t("音色与目标语言不匹配，请选择适合的音色或修改目标语言。")}</p>}
        {selected && validIdentity && mode && <fieldset disabled={loading || !!error || !!overrideIssue} className="graph-param-section">
          <div className="graph-param-grid">{optionsFields(false)}
            {Object.values(delivery ?? {}).filter(item => item.support === 'direct').length > 1 && <Field label={t("演绎")}><select value={effective?.default_delivery ?? 'normal'} onChange={event => update({ default_delivery: event.target.value as Delivery })}>
              {Object.entries(deliveryNames).filter(([value]) => delivery?.[value]?.support === 'direct').map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </select></Field>}
            {emotion?.support === 'direct' && <Field label={t("情绪")}><select value={effective?.default_emotion ?? 'neutral'} onChange={event => update({ default_emotion: event.target.value })}>
              {Object.entries(emotionNames).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </select></Field>}
          </div>
          {fields.some(([key]) => key !== 'speed') && <details className="graph-speech-group"><summary>{t("更多引擎参数")}</summary><div className="graph-param-grid">{optionsFields(true)}</div></details>}
        </fieldset>}
        {selected && !!node.options.speech_overrides && <button type="button" disabled={loading || !!error} onClick={() => requestChange(withSpeechOverrides(node, {}), '清除本次微调并恢复音色默认值？')}>{t("恢复音色默认值")}</button>}
        {issue && <p role="alert">{t(issue)}</p>}
        {extraData && <p role="alert">{t("含未识别参数，请在音色库核对后再运行。原值见下方。")}</p>}
        {(legacy || extraData || overrideIssue) && <details><summary>{t("保留的旧配置")}</summary><pre>{JSON.stringify({ provider: node.provider, model: node.model, options: node.options, provider_options: node.provider_options }, null, 2)}</pre></details>}
        {notice && <p role="status">{t(notice)}</p>}
        {error && <button type="button" onClick={() => setRevision(value => value + 1)}>{t("重试")}</button>}
      </div>}
  </div>
}

function Option({ name, field, value, reason, onChange }: { name: string; field: OptionSchema; value: unknown; reason: string; onChange: (value: unknown) => void }) {
  useI18n()
  const id = useId(), current = value ?? field.default, numeric = ['number', 'integer'].includes(field.type ?? '')
  return <div className="graph-param-field"><label htmlFor={id}>{optionNames[name] ? t(optionNames[name]!) : t(speechProviderText(field.title || name))}</label>
    {field.type === 'boolean' ? <input id={id} type="checkbox" checked={current === true} disabled={!!reason} onChange={event => onChange(event.target.checked)} />
      : field.enum ? <select id={id} value={String(current ?? '')} disabled={!!reason} onChange={event => onChange(numeric ? Number(event.target.value) : event.target.value)}>{field.enum.map(item => <option key={String(item)} value={String(item)}>{String(item)}</option>)}</select>
        : <input id={id} type={numeric ? 'number' : 'text'} value={String(current ?? '')} disabled={!!reason} min={field.minimum} max={field.maximum} maxLength={field.maxLength} step={field.type === 'integer' ? 1 : 'any'}
          onChange={event => onChange(event.target.value === '' ? undefined : numeric ? Number(event.target.value) : event.target.value)} />}
    {reason && <small>{t(reason)}</small>}
    {field.description && <details><summary>{t("说明")}</summary><small>{t(speechProviderText(field.description))}</small></details>}
  </div>
}
