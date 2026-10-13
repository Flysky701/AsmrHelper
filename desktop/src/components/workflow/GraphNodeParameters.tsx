import { speechProviderText } from '@/locales/voices'
import { t, format, useI18n } from '@/i18n'
import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import QwenReferenceMode from '@/components/QwenReferenceMode'
import FishVoicePicker from '@/components/FishVoicePicker'
import GraphEngineControl from './GraphEngineControl'
import SpeechPresetParameters from './SpeechPresetParameters'
import SpeechConnectionManager from '@/components/SpeechConnectionManager'
import { restoreEngineDraft } from '@/domain/nodeEngineDrafts'
import { defaultSpeechConnection } from '@/domain/speechConnections'
import { capabilitiesApi } from '@/api/capabilities'
import { settingsApi } from '@/api/settings'
import type { SettingsView } from '@/api/settings'
import { speechApi } from '@/api/speech'
import type { Delivery, OptionSchema, ReferenceAsset, SpeechConnection, SpeechConnectionDefault, SpeechProvider, SpeechRecipe } from '@/api/speech'
import type { CapabilityDescriptorResponse, CapabilityOptionResponse } from '@/api/types'
import type { GraphLanguage, GraphNode } from '@/domain/workflowGraph'
import { GRAPH_MAX_MIX_TRACKS, graphMixTracks, isMultitrackMix } from '@/domain/workflowGraph'
import { copyRecipeToGraphNode, editableGraphOptions, freshGraphSpeechNode, graphNodeFromRecipe,
  graphCapabilityDisabledReason, graphCapabilityValue, graphSpeechIssue, graphSpeechOptionDisabledReason,
  graphMixOutputLength, graphMixOutputLengthOptions, addGraphMixTrack, removeGraphMixTrack, updateGraphMixTrack,
  parseGraphObjectOption, readGraphSpeechSource, retainedGraphOptions, setGraphOption, unknownGraphOptions, withGraphSpeechSource } from '@/domain/graphNodeParameters'
import type { GraphParameterSection, GraphSpeechSource } from '@/domain/graphNodeParameters'
import { availableSpeechOptions, speechLanguageMatches, speechCapabilities } from '@/domain/speechAdvancedOptions'
import './GraphNodeParameters.css'

interface Props { node: GraphNode; onChange: (node: GraphNode) => void; disabled?: boolean; section?: GraphParameterSection; allowStructureChanges?: boolean }
const languageNames: Record<GraphLanguage, string> = { zh: '中文', ja: '日语', en: '英语' }
const modeNames: Record<string, string> = { default: '引擎默认声音', builtin: '预设声音', hosted: '服务端音色', reference: '参考录音克隆', design: '声音描述' }
const deliveryNames = { normal: '自然', soft: '轻柔', whisper: '耳语' }
const emotionNames: Record<string, string> = { neutral: '自然', happy: '开心', sad: '悲伤', angry: '愤怒', excited: '兴奋', calm: '平静', nervous: '紧张', relaxed: '放松' }
const optionNames: Record<string, string> = { beam_size: '搜索宽度', batch_size: '批量大小', temperature: '采样温度', top_p: '采样范围', initial_prompt: '识别提示词', vad_filter: '语音活动过滤', no_speech_threshold: '无语音阈值', device_map: '运行设备', dtype: '模型精度', forced_aligner: '对齐模型', forced_aligner_kwargs: '对齐模型初始化参数', return_time_stamps: '对齐时间戳', max_alignment_chunk_seconds: '对齐分块时长（秒）', hotwords: '识别热词', vad_kwargs: 'VAD 参数', speed: '语速', tag_density: '标签密度', style_description: '风格描述', cfg_value: '引导强度', inference_timesteps: '推理步数', instructions: '合成指令', hub: '模型来源', device: '运行设备', sentence_timestamp: '句级时间戳', trust_remote_code: '允许模型自定义代码', vad_model: 'VAD 模型', attn_implementation: '注意力实现', max_inference_batch_size: '推理批量上限', max_new_tokens: '生成长度上限', context: '识别上下文' }
function Field({ label, children }: { label: string; children: ReactNode }) {
  useI18n()
  return <label className="graph-param-field"><span>{t(label)}</span>{children}</label>
}
function Advanced({ section, children }: { section: GraphParameterSection; children: ReactNode }) {
  useI18n()
  if (section === 'common') return null
  return section === 'all' ? <details className="graph-param-advanced"><summary>{t("高级参数")}</summary><div className="graph-param-section">{children}</div></details>
    : <div className="graph-param-section">{children}</div>
}
function Language({ node, field, onChange }: Props & { field: 'source_lang' | 'target_lang' }) {
  useI18n()
  return <Field label={field === 'source_lang' ? t("输入语言") : node.kind === 'tts' ? t("合成目标语言") : t("目标语言")}><select value={node[field] ?? ''}
    onChange={event => onChange({ ...node, [field]: event.target.value || null })}>
    <option value="">{t("选择语言")}</option>{Object.entries(languageNames).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
  </select></Field>
}

/** Keying the local metadata panel prevents a late response or pending confirmation crossing nodes. */
export default function GraphNodeParameters(props: Props) {
  useI18n()
  return <NodeParameters key={`${props.node.id}:${props.node.kind}`} {...props} />
}

function NodeParameters({ node, onChange, disabled = false, section = 'all', allowStructureChanges = false }: Props) {
  useI18n()
  const common = section !== 'advanced'
  const mixOutputLength = graphMixOutputLength(node)
  const mixOutputLengthChoice = graphMixOutputLengthOptions.find(option => option.value === mixOutputLength)
  const [pending, setPending] = useState<{ description: string; node: GraphNode; base: GraphNode } | null>(null)
  const [switchNotice, setSwitchNotice] = useState('')
  const engineDrafts = useRef(new Map<string, GraphNode>())
  const speechDrafts = useRef(new Map<string, GraphNode>())
  const previousNode = useRef(node)
  const expectedNode = useRef<string | null>(null)
  if (previousNode.current !== node) {
    // Store callbacks clone our updates. Any other replacement, even equal-looking
    // node data from another preset, invalidates this editor's private drafts.
    if (expectedNode.current !== JSON.stringify(node)) { engineDrafts.current.clear(); speechDrafts.current.clear() }
    previousNode.current = node; expectedNode.current = null
  }
  const applyNode = (next: GraphNode) => { expectedNode.current = JSON.stringify(next); onChange(next) }
  const requestChange = (next: GraphNode, description: string) => setPending({ node: next, description, base: node })
  const requestEngineChange = (next: GraphNode) => {
    const restored = engineDrafts.current.has(next.provider)
    const candidate = restoreEngineDraft(node, next, engineDrafts.current)
    requestChange(candidate, `${restored ? '恢复' : '切换到'} ${candidate.provider} / ${candidate.model || '—'}？确认前仍使用 ${node.provider}。切回可恢复本次草稿。`)
  }
  const scopedChange = (next: GraphNode) => { setPending(null); applyNode(next) }
  return <div className="graph-node-parameters" data-node-id={node.id}>
    <fieldset disabled={disabled}>
      {pending && <section className="graph-param-confirm" aria-label={t("确认节点参数变更")}>
        <p>{t(pending.description)} {t(" 仅修改此节点。")}</p>
        <div className="graph-param-actions"><button type="button" onClick={() => { if (pending.base !== node) { setPending(null); setSwitchNotice('节点参数已变化，请重新选择引擎或模式。'); return }; applyNode(pending.node); setPending(null); setSwitchNotice('已更新此节点。') }}>{t("确认更换")}</button>
          <button type="button" onClick={() => setPending(null)}>{t("取消")}</button></div>
      </section>}
      {common && node.kind === 'align' && <>
        <GraphEngineControl provider={node.provider} model={node.model && node.model !== 'default' ? node.model : 'qwen3-forced-aligner-0.6b'} category="asr"
          choices={[{ id: 'qwen3_forced_aligner', name: 'Qwen3 Forced Aligner 0.6B' }]} local
          unavailable={node.provider !== 'qwen3_forced_aligner' || ![null, 'default', 'qwen3-forced-aligner-0.6b'].includes(node.model)}
          connectionSummary={t("使用模型的托管运行环境；需对应音频与字幕。")} onSelect={() => {}} onRefresh={() => {}} />
        <Language node={node} field="source_lang" onChange={scopedChange} />
      </>}
      {['asr', 'translate', 'separate'].includes(node.kind)
        && <CapabilityParameters node={node} onChange={scopedChange} requestChange={requestChange} requestEngineChange={requestEngineChange} section={section} />}
      {node.kind === 'tts' && <SpeechPresetParameters node={node} onChange={scopedChange} requestChange={requestChange} section={section} />}
      {common && node.kind === 'align' && <p className="graph-param-note">{t("Qwen3 Forced Aligner 0.6B · 需要匹配的音频与字幕。")}</p>}
      {common && isMultitrackMix(node) && <MixTrackParameters node={node} onChange={scopedChange} allowStructureChanges={allowStructureChanges} />}
      {node.kind === 'mix' && !isMultitrackMix(node) && <>
        {common && <div className="graph-param-grid">{([['original_volume', '音频轨音量', 0.85], ['tts_volume_ratio', '配音轨音量', 0.5]] as const).map(([key, label, fallback]) =>
          <Field key={key} label={t(label)}><input type="number" min={0} step={0.1} value={String(node.options[key] ?? fallback)}
            onChange={event => scopedChange(setGraphOption(node, 'options', key, event.target.value === '' ? undefined : Number(event.target.value)))} /></Field>)}</div>}
        {common && <Field label={t("输出时长")}><select value={mixOutputLength ?? String(node.options.output_length)}
          onChange={event => scopedChange(setGraphOption(node, 'options', 'output_length', event.target.value))}>
          {!mixOutputLength && <option value={String(node.options.output_length)}>{t("原设置（待确认）")}</option>}
          {graphMixOutputLengthOptions.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
        </select><small>{t(mixOutputLengthChoice?.description || "请选择有效的输出时长策略；原参数尚未更改。")}</small></Field>}
        <Advanced section={section}><Field label={t("配音延迟（毫秒）")}><input type="number" step={1} value={String(node.options.tts_delay_ms ?? 0)}
          onChange={event => scopedChange(setGraphOption(node, 'options', 'tts_delay_ms', event.target.value === '' ? undefined : Number(event.target.value)))} />
          <small>{t("正数后移，负数前移；前移会截去零点前的配音。")}</small></Field></Advanced>
        {common && <p className="graph-param-note">{t("两路音频需对应同一时间轴。")}</p>}
      </>}
      {node.kind === 'audio_difference' && <DifferenceParameters node={node} onChange={scopedChange} section={section} />}
      {common && node.kind === 'export' && <><Field label={t("目标字幕格式")}><select value={String(node.options.subtitle_format ?? 'srt')}
        onChange={event => scopedChange(setGraphOption(node, 'options', 'subtitle_format', event.target.value))}>
        {['srt', 'vtt', 'lrc'].map(format => <option key={format} value={format}>{format.toUpperCase()}</option>)}
      </select></Field><p className="graph-param-note">{t("将 SRT / VTT 素材或上游字幕转换为 SRT、VTT、LRC。保留文本；LRC 仅保留开始时间，精度为百分之一秒，多行合并为一行。")}</p></>}
      {common && node.kind === 'audio_export' && <p className="graph-param-note">{t("旧流程兼容：按原格式复制音频，不转码。新的音频产物可直接勾选交付。")}</p>}
      {switchNotice && <p role="status" className="graph-param-note">{t(switchNotice)}</p>}
    </fieldset>
  </div>
}

function MixTrackParameters({ node, onChange, allowStructureChanges }: Props) {
  useI18n()
  const tracks = graphMixTracks(node), length = graphMixOutputLength(node)
  return <div className="graph-param-section">
    <p className="graph-param-note">{t('各轨在输出时间轴上独立定位。音量 1 为原幅度；相加峰值超过上限时整体衰减至 0.98，保留轨道间音量比例。')}</p>
    {tracks.map(track => <section className="graph-mix-track" key={track.id} aria-label={format("音轨 · {0}", [track.id])}>
      <div className="graph-mix-track-heading"><strong>{t('音轨')}<small>{track.id}</small></strong>
        {allowStructureChanges && <button type="button" disabled={tracks.length <= 1} aria-label={format("删除音轨 {0}", [track.id])} onClick={() => onChange(removeGraphMixTrack(node, track.id))}>{t('删除轨道')}</button>}</div>
      <div className="graph-param-grid">
        <Field label={format("{0} 音量", [track.id])}><input type="number" min={0} step={0.1} value={String(track.gain ?? 1)} onChange={event => onChange(updateGraphMixTrack(node, track.id, { gain: event.target.value === '' ? undefined : Number(event.target.value) }))} /></Field>
        <Field label={format("{0} 偏移（毫秒）", [track.id])}><input type="number" step="any" value={String(track.offset_ms ?? 0)} onChange={event => onChange(updateGraphMixTrack(node, track.id, { offset_ms: event.target.value === '' ? undefined : Number(event.target.value) }))} /></Field>
      </div>
      <label className="graph-mix-mute"><input type="checkbox" checked={track.muted === true} onChange={event => onChange(updateGraphMixTrack(node, track.id, { muted: event.target.checked }))} />{format("{0} 静音", [track.id])}</label>
    </section>)}
    {allowStructureChanges ? <><button type="button" disabled={tracks.length >= GRAPH_MAX_MIX_TRACKS} onClick={() => onChange(addGraphMixTrack(node))}>{t('添加音轨')}</button><p className="graph-param-note">{t('支持 1–32 轨。删除轨道会移除其输入连线；新增轨道后请指定来源。')}</p></>
      : <p className="graph-param-note">{t('增删音轨与修改连线请进入流水线编辑页。')}</p>}
    <Field label="输出时长"><select value={length ?? String(node.options.output_length)} onChange={event => onChange(setGraphOption(node, 'options', 'output_length', event.target.value))}>
      {!length && <option value={String(node.options.output_length)}>{t('原设置（待确认）')}</option>}
      <option value="longest">{t('保留最长轨道（默认）')}</option><option value="main">{t('跟随第一轨')}</option>
    </select><small>{t(length === 'main' ? '跟随列表第一轨偏移后的结束位置；其他轨道超出部分截断。' : '按所有轨道偏移后的最晚结束位置输出，空缺补静音。静音轨道仍参与时长计算。')}</small></Field>
    <p className="graph-param-note">{t('正偏移延后，负偏移提前并截去零点前的音频。输入素材可来自不同录音，不自动做响度匹配。')}</p>
  </div>
}

function DifferenceParameters({ node, onChange, section = 'all' }: Props) {
  useI18n()
  const automatic = node.options.alignment === 'auto', matchGain = node.options.match_gain === true
  const change = (key: string, value: unknown) => onChange(setGraphOption(node, 'options', key, value))
  const number = (key: string, label: string, fallback: number | undefined, disabled = false, min?: number, max?: number) => <Field key={key} label={label}>
    <input type="number" step="any" min={min} max={max} disabled={disabled} value={String(node.options[key] ?? fallback ?? '')}
      placeholder={key === 'calibration_end' ? t('音频末尾') : undefined} onChange={event => change(key, event.target.value === '' ? undefined : Number(event.target.value))} />
  </Field>
  return <div className="graph-param-section">
    {section !== 'advanced' && <>
      <p className="graph-param-note">{t('含附加音效音频 − 对齐并调整增益后的基准音频。两路须是同源的有／无音效版本。')}</p>
      <Field label="时间对齐"><select value={String(node.options.alignment ?? 'manual')} onChange={event => change('alignment', event.target.value)}>
        {!['manual', 'auto'].includes(String(node.options.alignment ?? 'manual')) && <option value={String(node.options.alignment)}>{t('原设置（待确认）')}</option>}
        <option value="manual">{t('手动指定偏移')}</option><option value="auto">{t('自动估计固定偏移')}</option>
      </select></Field>
      {number('offset_ms', '基准音频偏移（毫秒）', 0, automatic)}
      <p className="graph-param-note">{t('正值延后基准，负值提前基准。')}{t(automatic ? '自动估计替代手动偏移，保存的手动值不叠加。' : '偏移以含附加音效音频的时间轴为准。')}</p>
      <label className="graph-mix-mute"><input type="checkbox" checked={matchGain} onChange={event => change('match_gain', event.target.checked)} />{t('自动匹配基准增益')}</label>
      <div className="graph-param-grid">{number('gain_left', '左声道／单声道增益', 1, matchGain)}{number('gain_right', '右声道增益', 1, matchGain)}</div>
      <p className="graph-param-note">{t(matchGain ? '自动拟合替代手动增益，手动值保留。' : '增益 1 保持幅度；负值用于极性反转。')}</p>
      <p className="graph-param-note">{t('输出浮点 WAV 保留差分幅值。不同母带、压缩、混响或时间漂移可能留下残留；这不是通用 AI 源分离。')}</p>
    </>}
    <Advanced section={section}>
      <div className="graph-param-grid">{number('calibration_start', '校准开始（秒）', 0, false, 0)}{number('calibration_end', '校准结束（秒，可留空）', undefined, false, 0)}</div>
      {number('max_shift_seconds', '自动对齐搜索范围（±秒）', 5, !automatic, .01, 30)}
      <p className="graph-param-note">{t('校准区间使用含附加音效音频的时间轴，尽量选没有附加音效的片段，用于自动对齐和增益拟合。留空结束时间使用可用音频末尾；附加音效进入校准区间可能被误消。自动对齐只估计固定偏移。')}</p>
    </Advanced>
  </div>
}

interface EditorProps extends Props { requestChange: (node: GraphNode, description: string) => void; requestEngineChange: (node: GraphNode) => void; requestSpeechChange?: (node: GraphNode, description: string) => void }
function CapabilityParameters({ node, onChange, requestChange, requestEngineChange, section = 'all' }: EditorProps) {
  useI18n()
  const common = section !== 'advanced'
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
  const retained = descriptor ? retainedGraphOptions(node, descriptor) : []
  const [chooseConnection, setChooseConnection] = useState(false)
  const connectionRef = typeof node.options.connection_ref === 'string' ? node.options.connection_ref : ''
  const connections = settings?.connection_profiles.llm ?? []
  const selectedConnection = connections.find(item => item.id === connectionRef)
  const defaultConnection = connections.find(item => item.id === settings?.connection_profiles.active_llm)
  const changeProvider = (provider: string) => {
    const next = descriptors.find(item => item.provider === provider)
    if (next && provider !== node.provider) requestEngineChange({ ...node, provider, model: next.default_model, options: node.kind === 'separate' ? { mode: 'vocals' } : {}, provider_options: {} })
  }
  const matchingConnections = connections.filter(item => item.provider === node.provider)
  const currentConnectionValid = selectedConnection?.provider === node.provider
  const connectionControl = <>
    <Field label={t("翻译服务连接")}><select value={connectionRef} onChange={event => {
      if (matchingConnections.some(item => item.id === event.target.value)) onChange(setGraphOption(node, 'options', 'connection_ref', event.target.value))
    }}><option value="" disabled>{t("选择此引擎的已保存连接")}</option>
      {connectionRef && !currentConnectionValid && <option value={connectionRef}>{connectionRef}{t("（不匹配或已缺失）")}</option>}
      {matchingConnections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></Field>
    {defaultConnection?.provider === node.provider ? <button type="button" onClick={() => requestChange({ ...node, model: defaultConnection.model || null,
      options: { ...node.options, connection_ref: defaultConnection.id } }, '使用设置中的全局默认连接及其模型；当前节点其他参数保持不变。')}>{t("使用当前全局默认连接和模型")}</button>
      : defaultConnection ? <p className="graph-param-note">{t("全局默认连接属于 ")}{defaultConnection.provider}{t("，不会替代当前引擎的连接。")}</p> : <p className="graph-param-note">{t("尚未设置全局默认翻译连接。")}</p>}
    {selectedConnection && <p className="graph-param-note">{selectedConnection.base_url} · {selectedConnection.credential_configured ? t("凭据已配置，服务未验证") : t("凭据未配置")}</p>}
  </>
  return <div className="graph-param-section">
    {loading && <p role="status">{t("正在读取节点能力…")}</p>}
    {error && <p role="alert">{t(error)}</p>}
    <fieldset disabled={loading || !!error}>
      {common && <>
        <GraphEngineControl provider={node.provider} model={node.model || selectedConnection?.model || descriptor?.default_model || null} category={category}
          choices={descriptors.map(item => ({ id: item.provider, name: item.display_name }))} local={descriptor?.kind === 'local'} loading={loading} unavailable={!descriptor || !!error}
          connectionSummary={node.kind === 'translate' ? currentConnectionValid ? format("节点指定：{0}{1}", [selectedConnection.name, defaultConnection?.id === selectedConnection.id ? t(" · 当前全局默认") : '']) : t("未绑定当前引擎的有效连接") : t("使用此模型的托管运行环境；运行环境在资源管理页配置。")}
          connectionIssue={node.kind === 'translate' && !currentConnectionValid ? t("请选择同引擎连接；不会自动使用其他引擎的全局默认。") : undefined}
          configurationKey={JSON.stringify([node.options, node.provider_options, selectedConnection])} configuration={node.kind === 'translate' ? connectionControl : undefined}
          onSelect={changeProvider} onRefresh={() => setRevision(value => value + 1)} />
        {['asr', 'translate'].includes(node.kind) && <div className="graph-param-grid"><Language node={node} field="source_lang" onChange={onChange} />{node.kind === 'translate' && <Language node={node} field="target_lang" onChange={onChange} />}</div>}
        <Field label={t("模型")}><input list={`graph-model-${node.id}`} value={node.model ?? ''} placeholder={selectedConnection?.model || descriptor?.default_model || t("使用连接或默认模型")}
          onChange={event => onChange({ ...node, model: event.target.value || null })} /><datalist id={`graph-model-${node.id}`}>{descriptor?.supported_models.map(model => <option key={model} value={model} />)}</datalist></Field>
        {node.kind === 'translate' && <>
          {currentConnectionValid && <button type="button" aria-expanded={chooseConnection} onClick={() => setChooseConnection(value => !value)}>{t("更换此节点连接")}</button>}
          {(!currentConnectionValid || chooseConnection) && connectionControl}
        </>}
        {node.kind === 'separate' && <p className="graph-param-note">{t("输出人声轨")}</p>}
      </>}
      <Advanced section={section}>
      {descriptor && ['asr', 'translate'].includes(node.kind) && (['options', 'provider_options'] as const).map(scope => {
        const fields = editableGraphOptions(scope === 'options' ? descriptor.common_option_schema : descriptor.provider_option_schema)
        return fields.length > 0 && <div className="graph-param-grid" key={scope}>{fields.map(field =>
          <CapabilityField key={field.name} node={node} field={field} value={node[scope][field.name]} onChange={value => onChange(setGraphOption(node, scope, field.name, value))} />)}</div>
      })}
      {retained.length > 0 && <p className="graph-param-note">{t("已保留扩展参数，此界面不编辑：")}{retained.join('、')}。</p>}
      {unknown.length > 0 && <div role="alert"><p>{t("能力声明不支持这些参数：")}{unknown.join('、')}{t("。原值保留，运行仍需通过后端校验。")}</p>
        <button type="button" onClick={() => requestChange({ ...node,
          options: Object.fromEntries(Object.entries(node.options).filter(([key]) => !unknown.includes(`options.${key}`))),
          provider_options: Object.fromEntries(Object.entries(node.provider_options).filter(([key]) => !unknown.includes(`provider_options.${key}`))) }, '移除显示的不支持参数。')}>{t("移除这些参数")}</button></div>}
      <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>{t("刷新能力信息")}</button>
      </Advanced>
    </fieldset>
    {error && <button type="button" onClick={() => setRevision(value => value + 1)}>{t("重试")}</button>}
  </div>
}

function CapabilityField({ node, field, value, onChange }: { node: GraphNode; field: CapabilityOptionResponse; value: unknown; onChange: (value: unknown) => void }) {
  useI18n()
  const current = graphCapabilityValue(node, field, value)
  const disabledReason = graphCapabilityDisabledReason(node, field.name)
  const id = useId()
  const fallback = node.provider === 'qwen3_asr' && field.name === 'device_map' ? '自动选择可用设备'
    : node.provider === 'qwen3_asr' && field.name === 'dtype' ? '未指定，由模型加载器决定'
      : node.provider === 'qwen3_asr' && field.name === 'forced_aligner'
        ? node.provider_options.return_time_stamps === true ? 'qwen3-forced-aligner-0.6b（时间戳已开启）' : '未启用对齐模型'
        : current == null ? '未显式设置' : format('引擎默认：{0}', [typeof current === 'boolean' ? t(current ? '开启' : '已关闭') : String(current)])
  return <div className="graph-param-field"><label htmlFor={id}>{t(optionNames[field.name] || field.name)}{field.required ? t("（必填）") : ''}</label>
    {field.type === 'object' ? <ObjectOption id={id} value={value} fallback={field.default} onChange={onChange} />
      : field.type === 'array' && field.name === 'hotwords' ? <HotwordsOption id={id} value={value} onChange={onChange} />
      : field.type === 'boolean' ? <input id={id} type="checkbox" disabled={!!disabledReason} checked={current === true} onChange={event => onChange(event.target.checked)} />
      : field.enum.length ? <select id={id} value={String(current ?? '')} onChange={event => onChange(field.enum.find(item => String(item) === event.target.value))}>
        <option value="">{t("引擎默认")}</option>{field.enum.map(item => <option key={String(item)} value={String(item)}>{String(item)}</option>)}
      </select> : <input id={id} type={['number', 'integer'].includes(field.type) ? 'number' : 'text'} value={String(current ?? '')}
        placeholder={t(fallback)}
        min={field.min ?? undefined} max={field.max ?? undefined} step={field.type === 'integer' ? 1 : 'any'}
        onChange={event => onChange(event.target.value === '' ? undefined : ['number', 'integer'].includes(field.type) ? Number(event.target.value) : event.target.value)} />}
    {disabledReason ? <small>{t(disabledReason)}</small> : value === undefined && !['object', 'array'].includes(field.type) && <small>{t(fallback)} {t(" · 未显式设置")}</small>}
    {value !== undefined && !disabledReason && <button type="button" className="graph-param-reset" onClick={() => onChange(undefined)}>{t("恢复默认")}</button>}
    {field.description && <details className="graph-param-help"><summary>{t("参数说明")}</summary><small>{field.description}</small></details>}
  </div>
}

function ObjectOption({ id, value, fallback, onChange }: { id: string; value: unknown; fallback: unknown; onChange: (value: unknown) => void }) {
  useI18n()
  const [draft, setDraft] = useState<string | null>(null)
  const parsed = draft === null ? {} : parseGraphObjectOption(draft)
  return <div className="graph-param-structured">
    {draft === null ? <><code>{value === undefined ? format("未显式设置{0}", [fallback == null ? '' : format(" · 默认 {0}", [JSON.stringify(fallback)])]) : JSON.stringify(value)}</code>
      <button id={id} type="button" onClick={() => setDraft(JSON.stringify(value ?? fallback ?? {}, null, 2))}>{t("编辑对象")}</button></>
      : <><textarea id={id} aria-label={t("JSON 对象参数")} rows={5} value={draft} onChange={event => setDraft(event.target.value)} />
        {parsed.error && <p role="alert">{t(parsed.error)}</p>}
        <small>{t("仅检查 JSON 对象格式；内部字段由对应引擎校验。保存前保持原值。")}</small>
        <div className="graph-param-actions"><button type="button" disabled={!!parsed.error} onClick={() => { onChange(parsed.value); setDraft(null) }}>{t("保存对象")}</button>
          <button type="button" onClick={() => setDraft(null)}>{t("取消")}</button></div></>}
  </div>
}

function HotwordsOption({ id, value, onChange }: { id: string; value: unknown; onChange: (value: unknown) => void }) {
  useI18n()
  const [draft, setDraft] = useState<string[] | null>(null)
  const valid = value === undefined || Array.isArray(value) && value.every(item => typeof item === 'string')
  return <div className="graph-param-structured">
    {draft === null ? <><p>{value === undefined ? t("未设置热词") : valid ? (value as string[]).join('、') || t("空热词列表") : t("原值已保留，当前界面仅编辑字符串列表。")}</p>
      {!valid && <code>{JSON.stringify(value)}</code>}
      <button id={id} type="button" onClick={() => setDraft(valid && Array.isArray(value) ? [...value] : [])}>{t("编辑热词")}</button></>
      : <><div className="graph-param-hotwords">{draft.map((word, index) => <div key={index} className="graph-param-hotword"><input aria-label={format("热词 {0}", [index + 1])} value={word}
        onChange={event => setDraft(draft.map((item, position) => position === index ? event.target.value : item))} />
        <button type="button" aria-label={format("删除热词 {0}", [index + 1])} onClick={() => setDraft(draft.filter((_, position) => position !== index))}>{t("删除")}</button></div>)}</div>
        <div className="graph-param-actions"><button type="button" onClick={() => setDraft([...draft, ''])}>{t("添加热词")}</button>
          <button type="button" onClick={() => { onChange(draft); setDraft(null) }}>{t("保存热词")}</button>
          <button type="button" onClick={() => setDraft(null)}>{t("取消")}</button></div></>}
  </div>
}

/** Retained during the preset migration; new nodes use SpeechPresetParameters. */
export function LegacySpeechParameters({ node, onChange, requestChange, requestEngineChange, requestSpeechChange = requestChange, section = 'all' }: EditorProps) {
  useI18n()
  const common = section !== 'advanced'
  const [providers, setProviders] = useState<SpeechProvider[]>([])
  const [recipes, setRecipes] = useState<SpeechRecipe[]>([])
  const [assets, setAssets] = useState<ReferenceAsset[]>([])
  const [connections, setConnections] = useState<SpeechConnection[]>([])
  const [defaults, setDefaults] = useState<SpeechConnectionDefault[]>([])
  const [connectionChoice, setConnectionChoice] = useState(false)
  const latestNode = useRef(node)
  latestNode.current = node
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [previewId, setPreviewId] = useState('')
  const [choosingPreset, setChoosingPreset] = useState(false)
  const [copyError, setCopyError] = useState('')
  const voiceList = useId()
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    Promise.all([speechApi.providers(), speechApi.rules(), speechApi.references(), speechApi.connections()])
      .then(([catalog, rules, references, connectionList]) => {
        if (!active) return
        setProviders(catalog.providers); setRecipes(rules.recipes.filter(item => !item.archived))
        setAssets(references.assets.filter(item => !item.archived)); setConnections(connectionList.connections); setDefaults(connectionList.defaults || [])
      }).catch(() => { if (active) setError('声音能力、已保存预设或素材读取失败，请重试。当前节点设置仍保留。') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [revision])
  const provider = providers.find(item => item.provider_id === node.provider)
  const source = readGraphSpeechSource(node)
  // Presentation state belongs to this exact engine/model/source, not just the node ID.
  useEffect(() => {
    setPreviewId(''); setChoosingPreset(false); setCopyError(''); setConnectionChoice(false)
  }, [node.provider, node.model, source?.mode, node.options.speech_recipe_id])
  const selected = recipes.find(item => item.id === node.options.speech_recipe_id)
  const recipeMismatch = !!selected && (selected.provider_id !== node.provider || selected.model !== node.model)
  const recipeConnection = selected && connections.find(item => item.id === selected.connection_ref && item.provider_id === selected.provider_id)
  const recipeProvider = selected && providers.find(item => item.provider_id === selected.provider_id)
  const recipeConnectionMissing = selected && !recipeConnection && (recipeProvider?.connection_required || !!selected.connection_ref && selected.connection_ref !== `engine-default-${selected.provider_id}`)
  const recipeConnectionName = recipeConnection?.name || t(recipeProvider && !recipeProvider.connection_required && (!selected?.connection_ref || selected.connection_ref === `engine-default-${selected.provider_id}`) ? '引擎默认连接' : '连接待确认')
  const preview = recipes.find(item => item.id === previewId)
  const models = [...new Set(provider?.modes.flatMap(item => item.models) ?? [])]
  const modes = provider?.modes.filter(item => !item.models.length || item.models.includes(node.model ?? '')) ?? []
  const mode = modes.find(item => item.id === source?.mode)
  const compatibleSource = !!source && !!mode && mode.variant_kinds.includes(source.variant.kind)
  const catalog = compatibleSource ? mode?.voice_sources : undefined
  const matchingConnections = connections.filter(item => item.provider_id === node.provider)
  const selectedConnection = matchingConnections.find(item => item.id === source?.connection_ref)
  const defaultConnection = defaultSpeechConnection(node.provider, connections, defaults)
  useEffect(() => {
    // Bind an unbound inline draft once. Saved recipes and even missing explicit IDs stay untouched.
    const current = latestNode.current, currentSource = readGraphSpeechSource(current)
    if (loading || error || !defaultConnection || current.provider !== defaultConnection.provider_id
      || current.options.speech_recipe_id || !currentSource || currentSource.connection_ref) return
    onChange(withGraphSpeechSource(current, { ...currentSource, connection_ref: defaultConnection.id }))
  }, [loading, error, defaultConnection?.id, node.provider, node.options.speech_recipe_id, source?.connection_ref, onChange])
  const reference = compatibleSource && source?.variant.kind === 'reference' ? assets.find(item => item.id === source.variant.value) : undefined
  const issue = loading || error ? '' : graphSpeechIssue(node, provider, recipes, assets, connections)
  const updateSource = (patch: Partial<GraphSpeechSource>) => { if (source) onChange(withGraphSpeechSource(node, { ...source, ...patch })) }
  const changeValue = (value: string) => { if (source) updateSource({ variant: { ...source.variant, value } }) }
  const capabilities = compatibleSource ? speechCapabilities(provider, source?.mode ?? '', node.model ?? '') : undefined
  const deliveryCaps = capabilities?.delivery as Record<string, { support?: string }> | undefined
  const emotionCaps = capabilities?.emotion as { support?: string } | undefined
  const fields = compatibleSource ? availableSpeechOptions(provider, source?.mode ?? '', node.model ?? '') : []
  const commonKeys = new Set(['speed', 'x_vector_only_mode'])
  const deliveryChoices = Object.entries(deliveryNames).filter(([value]) => value === 'normal' || deliveryCaps?.[value]?.support === 'direct' || value === source?.variant.style || value === source?.default_delivery)
  const connectionMissing = source && (!selectedConnection && !!source.connection_ref && source.connection_ref !== `engine-default-${node.provider}` || provider?.connection_required && !selectedConnection)
  const connectionControl = source && <Field label={t("声音运行连接")}><select value={source.connection_ref ?? ''} onChange={event => { if (event.target.value) updateSource({ connection_ref: event.target.value }) }}>
    <option value="" disabled>{t("选择已保存连接")}</option>
    {source.connection_ref && source.connection_ref !== `engine-default-${node.provider}` && !selectedConnection && <option value={source.connection_ref}>{source.connection_ref === `engine-default-${node.provider}` ? t("引擎默认环境") : format("{0}（原连接已缺失，需重选）", [source.connection_ref])}</option>}
    {provider && !provider.connection_required && <option value={`engine-default-${node.provider}`}>{t("明确使用引擎默认环境")}</option>}
    {matchingConnections.map(item => <option key={item.id} value={item.id}>{item.name}{item.id === defaultConnection?.id ? t("（此引擎默认）") : ''}</option>)}
  </select></Field>
  const speechFields = (isCommon: boolean) => source && fields.filter(([key]) => commonKeys.has(key) === isCommon).map(([key, field]) => {
    const update = (value: unknown) => { const provider_options = { ...source.provider_options }; if (value === undefined) delete provider_options[key]; else provider_options[key] = value; updateSource({ provider_options }) }
    return provider?.provider_id === 'qwen3' && source.mode === 'reference' && key === 'x_vector_only_mode'
      ? <QwenReferenceMode key={key} className="graph-param-field" value={source.provider_options[key] === true} onChange={update} />
      : <SpeechOption key={key} name={key} field={field} value={source.provider_options[key]} disabledReason={graphSpeechOptionDisabledReason(node, source, key)} onChange={update} />
  })
  return <div className="graph-param-section">
    {loading && <p role="status">{t("正在读取语音能力和已保存素材…")}</p>}
    {error && <p role="alert">{t(error)}</p>}
    <fieldset disabled={loading || !!error}>
      {common && <>
      <GraphEngineControl provider={node.provider} model={node.model} category="tts" choices={providers.map(item => ({ id: item.provider_id, name: item.name }))}
        local={provider?.remote === false} connectionRequired={provider?.connection_required} loading={loading} unavailable={!provider || !!error}
        connectionSummary={node.options.speech_recipe_id ? format("音色预设：{0} · {1}", [selected?.name || String(node.options.speech_recipe_id), recipeConnectionName]) : selectedConnection ? format("节点指定：{0}{1}", [selectedConnection.name, selectedConnection.id === defaultConnection?.id ? t(" · 此引擎默认") : '']) : t("使用引擎默认环境或待选择连接")}
        connectionIssue={recipeMismatch ? t("音色预设的引擎或模型与此节点不一致。请重新应用声音预设，或点击“复制为本节点参数并编辑”；确认一致前不检查连接。") : source && !compatibleSource ? t("声音来源与当前引擎模型不兼容。请在参数面板点击“重新配置声音来源”，确认后再检查连接。") : node.options.speech_recipe_id ? !selected ? t("原音色预设不可用，请在“更换声音预设”中重新选择。") : recipeConnectionMissing ? t("此音色预设的连接已缺失。请点击“复制为本节点参数并编辑”，再为此节点选择连接；原音色预设保持不变。") : undefined : connectionMissing ? t("此节点没有匹配当前引擎的连接。请打开“配置当前节点”，在“声音运行连接”中重选；选择后立即更新当前节点，无需安装模型或环境。") : undefined}
        configurationKey={JSON.stringify([node.options.speech_recipe_id, source, selected, selectedConnection, recipeConnection])}
        checkConfiguration={!recipeMismatch && (!source || compatibleSource) && (recipeConnection || selectedConnection) ? () => speechApi.probe((recipeConnection || selectedConnection)!.id, node.model || '', selected?.mode || source?.mode || '') : undefined}
        configuration={<><p className="graph-param-note">默认变更不覆盖已绑定节点或已保存音色。缺失的旧引用需要明确重选。</p>{source && !node.options.speech_recipe_id && connectionControl}<SpeechConnectionManager connections={connections} defaults={defaults} providers={providers} providerId={node.provider} onChanged={async () => { const [next, rules] = await Promise.all([speechApi.connections(), speechApi.rules()]); setConnections(next.connections); setDefaults(next.defaults || []); setRecipes(rules.recipes.filter(item => !item.archived)) }} /></>}
        onSelect={value => { const next = providers.find(item => item.provider_id === value); if (next && value !== node.provider) requestEngineChange(freshGraphSpeechNode(node, next)) }} onRefresh={() => setRevision(value => value + 1)} />
      <Language node={node} field="target_lang" onChange={onChange} />
      {capabilities?.language_control === 'automatic' && <p className="graph-param-note">{t('目标语言用于新台词，服务按文本自动识别语言。')}</p>}
      {(!source && !node.options.speech_recipe_id || choosingPreset) ? <Field label={t("声音预设")}><select value={previewId} onChange={event => { setPreviewId(event.target.value); setCopyError('') }}>
        <option value="">{t("选择已保存预设，预览后应用")}</option>{recipes.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></Field> : <button type="button" onClick={() => setChoosingPreset(true)}>{t("更换声音预设")}</button>}
      {preview && <section className="graph-param-confirm" aria-label={t("配音预设应用预览")}>
        <p>{preview.name} · {preview.provider_id} / {preview.model} · {t(modeNames[preview.mode] || preview.mode)} {t(" · 合成目标：")}{preview.language === 'auto' || !preview.language ? t("跟随本节点目标语言") : t(languageNames[preview.language as GraphLanguage] || preview.language)}</p>
        <p>{t("应用将替换此节点的声音来源、连接和合成参数，合成目标语言仍为 ")}{node.target_lang ? t(languageNames[node.target_lang]) : t("未选择")}{t("，不使用参考录音语言替代。")}</p>
        {!speechLanguageMatches(preview.language, node.target_lang ?? '') && <p role="alert">{t("预设合成目标语言与此节点不一致，请更换预设或自行调整目标语言。")}</p>}
        <div className="graph-param-actions"><button type="button" disabled={!speechLanguageMatches(preview.language, node.target_lang ?? '')}
          onClick={() => { onChange(graphNodeFromRecipe(node, preview)); setPreviewId(''); setChoosingPreset(false) }}>{t("应用到此节点")}</button><button type="button" onClick={() => setPreviewId('')}>{t("取消预览")}</button></div>
      </section>}
      {node.options.speech_recipe_id ? <section className="graph-param-section">
        <p className="graph-param-summary">{selected ? `${selected.name} · r${selected.revision}` : String(node.options.speech_recipe_id)}</p>
        {selected && <>
          <p className="graph-param-note">{recipeProvider?.name || selected.provider_id} · {selected.model} · {t(modeNames[selected.mode] || selected.mode)}</p>
          <p className="graph-param-note" title={selected.variant.value}>{selected.variant.kind === 'reference' ? assets.find(item => item.id === selected.variant.value)?.name || t("参考录音") : selected.variant.value || t("引擎默认声音")}</p>
          <button type="button" onClick={() => { try { onChange(copyRecipeToGraphNode(node, selected)); setCopyError('') } catch (cause) { setCopyError(String(cause instanceof Error ? cause.message : cause)) } }}>{t("复制为本节点参数并编辑")}</button>
        </>}
        {copyError && <p role="alert">{t(copyError)}</p>}
      </section> : null}
      </>}
      {common && !node.options.speech_recipe_id && <>
        {(models.length !== 1 || !models.includes(node.model ?? '')) && <Field label={t("声音模型")}>{models.length ? <select value={node.model ?? ''} onChange={event => {
          if (provider && event.target.value !== node.model) requestSpeechChange(freshGraphSpeechNode(node, provider, event.target.value, source?.mode), '更换声音模型将调整兼容的声音来源与参数。')
        }}><option value="" disabled>{t("选择模型")}</option>{node.model && !models.includes(node.model) && <option value={node.model}>{node.model}{t("（待确认）")}</option>}{models.map(model => <option key={model} value={model}>{model}</option>)}</select>
          : <input value={node.model ?? ''} placeholder={t("服务文档中的模型 ID")} onChange={event => onChange({ ...node, model: event.target.value || null })} />}</Field>}
        {source && (modes.length > 1 || !mode) && <Field label={t("声音来源")}><select value={source.mode} onChange={event => {
          if (provider && event.target.value !== source.mode) requestSpeechChange(freshGraphSpeechNode(node, provider, node.model ?? undefined, event.target.value), '更换声音模式将调整兼容的声音来源和高级参数；当前连接保留。')
        }}>{!mode && <option value={source.mode}>{source.mode}{t("（待确认）")}</option>}{modes.map(item => <option key={item.id} value={item.id}>{t(modeNames[item.id] || item.id)}</option>)}</select></Field>}
      </>}
      {!node.options.speech_recipe_id && <Advanced section={section}>
      {source && compatibleSource && <>
        <div className="graph-param-grid">{speechFields(false)}</div>
        <div className="graph-param-grid">
          {deliveryChoices.length > 1 && <Field label={t("默认演绎")}><select value={source.default_delivery ?? 'normal'} onChange={event => updateSource({ default_delivery: event.target.value as Delivery })}>
            {deliveryChoices.map(([value, label]) => <option key={value} value={value} disabled={value !== 'normal' && deliveryCaps?.[value]?.support !== 'direct' && value !== source.variant.style}>{t(label)}</option>)}
          </select></Field>}
          {(emotionCaps?.support === 'direct' || source.default_emotion && source.default_emotion !== 'neutral') && <Field label={t("默认情绪")}><select value={source.default_emotion ?? 'neutral'} onChange={event => updateSource({ default_emotion: event.target.value })}>
            {Object.entries(emotionNames).map(([value, label]) => <option key={value} value={value} disabled={value !== 'neutral' && emotionCaps?.support !== 'direct'}>{t(label)}</option>)}
          </select></Field>}
          <Field label={t("句后停顿（毫秒）")}><input type="number" min={0} max={30000} step={1} value={source.default_pause_ms ?? 0}
            onChange={event => updateSource({ default_pause_ms: event.target.value === '' ? undefined : Number(event.target.value) })} /></Field>
        </div>
      </>}
      <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>{t("刷新声音与连接")}</button>
      </Advanced>}
      {common && !node.options.speech_recipe_id && !source && provider && <button type="button" onClick={() => requestChange(freshGraphSpeechNode(node, provider, node.model && node.model !== 'default' ? node.model : undefined), '配置该引擎的明确声音来源将替换此节点已有简写声音参数。')}>{t("配置声音来源")}</button>}
      {common && !node.options.speech_recipe_id && source && !compatibleSource && provider && <button type="button" onClick={() => requestSpeechChange(freshGraphSpeechNode(node, provider, node.model && models.includes(node.model) ? node.model : undefined), '重新配置与当前引擎模型兼容的声音来源；确认后替换不兼容参数。')}>{t("重新配置声音来源")}</button>}
      {common && !node.options.speech_recipe_id && source && <>
        {matchingConnections.length > 1 && <div className="graph-param-actions"><button type="button" aria-expanded={connectionChoice} onClick={() => setConnectionChoice(value => !value)}>{t("更换运行配置")}</button></div>}
        {(connectionMissing || connectionChoice || !source.connection_ref && provider?.connection_required) && connectionControl}
        {compatibleSource && provider?.provider_id === 'fish_audio' && source.mode === 'hosted' && <FishVoicePicker connectionId={selectedConnection?.id || ''} value={source.variant.value} onSelect={changeValue} />}
        {catalog && provider?.provider_id !== 'fish_audio' && source.mode !== 'default' && <Field label={modeNames[source.mode] || t("声音来源")}>
          {source.variant.kind === 'reference' ? <select value={source.variant.value} onChange={event => changeValue(event.target.value)}>
            <option value="">{t("选择已保存参考录音")}</option>
            {source.variant.value && !reference && <option value={source.variant.value}>{t("原参考录音（不可用）")}</option>}
            {assets.map(item => <option key={item.id} value={item.id}>{item.name || item.id} · {item.language || t("语言未知")}</option>)}
          </select> : catalog.presets.length && !catalog.allow_custom ? <select value={source.variant.value} onChange={event => changeValue(event.target.value)}>
            {!catalog.presets.some(item => item.id === source.variant.value) && <option value={source.variant.value}>{source.variant.value || t("选择声音")}</option>}
            {catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
          </select> : source.mode === 'design' ? <textarea value={source.variant.value} rows={3} onChange={event => changeValue(event.target.value)} />
            : <><input list={voiceList} value={source.variant.value} onChange={event => changeValue(event.target.value)} placeholder={t(speechProviderText(catalog.description))} />
              <datalist id={voiceList}>{catalog.presets.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}</datalist></>}
        </Field>}
        {catalog?.description && provider?.provider_id !== 'fish_audio' && <details><summary>{t("声音来源说明")}</summary><p className="graph-param-note">{t(speechProviderText(catalog.description))}</p></details>}
        {reference && <div className="graph-param-reference"><p>{reference.name || reference.id} {t(" · 参考录音语言：")}{reference.language === 'auto' || !reference.language ? t("未明确") : t(languageNames[reference.language as GraphLanguage] || reference.language)} · {reference.confirmed ? t("原文已核对") : t("原文未确认")}</p>
          <audio controls preload="none" src={speechApi.referenceAudio(reference.id)} aria-label={t("试听所选参考录音")} />
          <p>{t("参考原文（不翻译）：")}{reference.transcript || t("未提供")}</p></div>}
        {fields.some(([key]) => commonKeys.has(key)) && <div className="graph-param-grid">{speechFields(true)}</div>}
      </>}
    </fieldset>
    {issue && !(common && (connectionMissing || recipeMismatch || source && !compatibleSource)) && <p role="alert">{t(issue)}</p>}
    {error && <button type="button" onClick={() => setRevision(value => value + 1)}>{t("重试")}</button>}
  </div>
}

function SpeechOption({ name, field, value, disabledReason, onChange }: {
  name: string; field: OptionSchema; value: unknown; disabledReason: string; onChange: (value: unknown) => void
}) {
  useI18n()
  const id = useId()
  const current = value ?? field.default
  const numeric = ['number', 'integer'].includes(field.type ?? '')
  return <div className="graph-param-field">
    <label htmlFor={id}>{optionNames[name] ? t(optionNames[name]!) : t(speechProviderText(field.title || name))}</label>
    {field.type === 'boolean' ? <input id={id} type="checkbox" checked={current === true} disabled={!!disabledReason} onChange={event => onChange(event.target.checked)} />
      : field.enum ? <select id={id} value={String(current ?? '')} disabled={!!disabledReason} onChange={event => onChange(numeric ? Number(event.target.value) : event.target.value)}>
        {field.enum.map(item => <option key={String(item)} value={String(item)}>{String(item)}</option>)}</select>
        : field.type === 'string' && (field.maxLength ?? 0) > 200 ? <textarea id={id} rows={3} maxLength={field.maxLength} value={String(current ?? '')} disabled={!!disabledReason} onChange={event => onChange(event.target.value || undefined)} />
          : <input id={id} type={numeric ? 'number' : 'text'} value={String(current ?? '')} disabled={!!disabledReason}
            min={field.minimum} max={field.maximum} step={field.type === 'integer' ? 1 : 'any'} maxLength={field.maxLength}
            onChange={event => onChange(event.target.value === '' ? undefined : numeric ? Number(event.target.value) : event.target.value)} />}
    {disabledReason && <small>{t(disabledReason)}</small>}
    {!disabledReason && field.description && <details className="graph-param-help"><summary>{t("参数说明")}</summary><small>{t(speechProviderText(field.description))}</small></details>}
  </div>
}
