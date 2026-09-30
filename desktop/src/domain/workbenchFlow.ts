import type { WorkflowReference, PipelineWorkflowRequest } from '@/api/types'
import type { PipelineStageId } from '@/domain/pipelinePreset'
import type { WorkbenchInputItem } from '@/domain/workbenchInput'

const STAGES: PipelineStageId[] = ['separate', 'asr', 'align', 'translate', 'tts', 'mix', 'export']
const LABELS: Record<PipelineStageId, string> = {
  separate: '人声分离', asr: '语音识别', align: '时间轴校准', translate: '字幕翻译',
  tts: '语音合成', mix: '混音输出', export: '字幕导出',
}
export const FLOW_PORTS: Record<PipelineStageId, Array<{ key: string; label: string; type: 'audio' | 'text' | 'speech' }>> = {
  separate: [{ key: 'audio', label: '原始音频', type: 'audio' }],
  asr: [{ key: 'audio', label: '识别音频', type: 'audio' }],
  align: [{ key: 'audio', label: '对齐音频', type: 'audio' }, { key: 'text', label: '待对齐字幕', type: 'text' }],
  translate: [{ key: 'text', label: '待翻译字幕', type: 'text' }],
  tts: [{ key: 'text', label: '配音字幕', type: 'text' }],
  mix: [{ key: 'audio', label: '混音底轨', type: 'audio' }, { key: 'speech', label: '叠加音轨', type: 'speech' }],
  export: [{ key: 'text', label: '导出字幕', type: 'text' }],
}
export const FLOW_OUTPUTS: Record<PipelineStageId, string> = {
  separate: '分离人声音频', asr: '识别文本', align: '校准字幕与时间轴',
  translate: '翻译文本', tts: '独立配音音频', mix: '混音成品音频', export: '字幕文件',
}
export type FlowDraft = PipelineWorkflowRequest & { selectedStages: PipelineStageId[]; subtitleFormat: 'srt' | 'vtt' }
export const emptyFlow = (): FlowDraft => ({ version: 1, selectedStages: [], bindings: {}, outputs: [], subtitleFormat: 'srt' })
export const FLOW_PRESETS = [
  { id: 'audio_subtitles', label: '音频转字幕', stages: ['asr', 'export'] },
  { id: 'subtitle_translation', label: '字幕翻译', stages: ['translate', 'export'] },
  { id: 'subtitle_speech', label: '目标字幕直接配音', stages: ['tts'] },
  { id: 'audio_translation_speech', label: '音频翻译配音', stages: ['asr', 'translate', 'tts', 'export'] },
] as const satisfies ReadonlyArray<{ id: string; label: string; stages: readonly PipelineStageId[] }>
const key = (path: string) => path.replace(/\\/g, '/').toLowerCase()
const language = (value?: string) => (value || '').toLowerCase().replace('-', '_').split('_')[0]!
const known = (value?: string) => !!value && !['unknown', 'mixed', 'auto'].includes(language(value))
export const materialKind = (item: WorkbenchInputItem) => item.kind || (/\.(srt|vtt|lrc)$/i.test(item.path) ? 'subtitle' : 'audio')

export function toggleFlowStage(flow: FlowDraft, stage: PipelineStageId): FlowDraft {
  const enabled = flow.selectedStages.includes(stage)
  return { ...flow,
    selectedStages: enabled ? flow.selectedStages.filter(id => id !== stage) : STAGES.filter(id => id === stage || flow.selectedStages.includes(id)),
    outputs: enabled ? flow.outputs.filter(id => id !== stage) : [...flow.outputs, stage],
  }
}

export function restoreFlow(value: unknown): FlowDraft {
  if (!value || typeof value !== 'object') return emptyFlow()
  const saved = value as Partial<FlowDraft>
  const selectedStages = STAGES.filter(id => saved.selectedStages?.includes(id))
  return { version: 1, selectedStages,
    bindings: saved.bindings && typeof saved.bindings === 'object' ? structuredClone(saved.bindings) : {},
    outputs: STAGES.filter(id => selectedStages.includes(id) && saved.outputs?.includes(id)),
    subtitleFormat: saved.subtitleFormat === 'vtt' ? 'vtt' : 'srt',
  }
}

/** Presets only change checkboxes, using the same output defaults as manual toggles. */
export function applyFlowPreset(flow: FlowDraft, presetId: string): FlowDraft {
  const preset = FLOW_PRESETS.find(item => item.id === presetId)
  if (!preset) return flow
  const selected = new Set<PipelineStageId>(preset.stages)
  return STAGES.reduce((draft, stage) => selected.has(stage) === draft.selectedStages.includes(stage)
    ? draft : toggleFlowStage(draft, stage), flow)
}

/** This matches steps only, never claims that materials, outputs or parameters are ready. */
export function matchingFlowPreset(flow: FlowDraft) {
  const selected = new Set(flow.selectedStages)
  return FLOW_PRESETS.find(preset => selected.size === preset.stages.length && preset.stages.every(stage => selected.has(stage)))
}

export function workflowPayload(flow: FlowDraft): PipelineWorkflowRequest {
  return { version: 1,
    bindings: Object.fromEntries(flow.selectedStages.map(id => [id, structuredClone(flow.bindings[id] || {})])),
    outputs: [...flow.outputs],
  }
}

export function referenceValue(ref?: WorkflowReference): string {
  return !ref ? '' : ref.kind === 'stage' ? `stage:${ref.stage}` : `asset:${ref.path}`
}

export function referenceFromValue(value: string): WorkflowReference | undefined {
  if (value.startsWith('stage:')) return { kind: 'stage', stage: value.slice(6) as PipelineStageId }
  if (value.startsWith('asset:')) return { kind: 'asset', path: value.slice(6) }
  return undefined
}

export function sourceOptions(stage: PipelineStageId, type: 'audio' | 'text' | 'speech', flow: FlowDraft, items: WorkbenchInputItem[]) {
  const allowed = type === 'text' ? ['asr', 'align', 'translate'] : type === 'speech' ? ['tts'] : ['separate']
  return [
    ...items.filter(item => materialKind(item) === (type === 'text' ? 'subtitle' : 'audio'))
      .map(item => ({ value: `asset:${item.path}`, label: items.some(other => other.path !== item.path && other.name === item.name) ? `${item.name} (${item.path})` : item.name, path: item.path })),
    ...STAGES.filter(id => STAGES.indexOf(id) < STAGES.indexOf(stage) && allowed.includes(id) && flow.selectedStages.includes(id))
      .map(id => ({ value: `stage:${id}`, label: `前序产物 · ${LABELS[id]}`, path: '' })),
  ]
}

export function assessFlow(flow: FlowDraft, items: WorkbenchInputItem[], sourceLang: string, targetLang: string) {
  const stages = Object.fromEntries(STAGES.map(id => [id, { issues: [] as string[], upstream: false }])) as Record<PipelineStageId, { issues: string[]; upstream: boolean }>
  const find = (path: string) => items.find(item => key(item.path) === key(path))
  const audioOrigin = (ref: WorkflowReference | undefined, visited = new Set<string>()): string => {
    if (!ref) return ''
    if (ref.kind === 'asset') return ref.path
    if (visited.has(ref.stage)) return ''
    visited.add(ref.stage)
    return audioOrigin(flow.bindings[ref.stage]?.audio, visited)
  }
  const textOrigin = (ref: WorkflowReference | undefined, visited = new Set<string>()): WorkflowReference | undefined => {
    if (!ref || ref.kind === 'asset') return ref
    if (visited.has(ref.stage)) return undefined
    visited.add(ref.stage)
    if (ref.stage === 'asr') return ref
    return textOrigin(flow.bindings[ref.stage]?.text, visited)
  }
  const textLanguage = (ref: WorkflowReference | undefined, visited = new Set<string>()): string => {
    if (!ref) return ''
    if (ref.kind === 'asset') {
      const detected = find(ref.path)?.subtitleSummary?.language
      return known(detected) ? language(detected) : ref.language_confirmed ? language(ref.language) : ''
    }
    if (visited.has(ref.stage)) return ''
    visited.add(ref.stage)
    if (ref.stage === 'asr') return language(sourceLang)
    if (ref.stage === 'translate') return language(targetLang)
    return textLanguage(flow.bindings[ref.stage]?.text, visited)
  }
  // A subtitle and an audio used together must refer to the same recording.
  for (const stage of ['align', 'mix'] as const) {
    if (!flow.selectedStages.includes(stage)) continue
    const audio = audioOrigin(flow.bindings[stage]?.audio)
    const speech = flow.bindings.mix?.speech
    const text = stage === 'align' ? flow.bindings.align?.text
      : speech?.kind === 'stage' && speech.stage === 'tts' ? flow.bindings.tts?.text : undefined
    const origin = textOrigin(text)
    if (!audio || !origin) continue
    if (origin.kind === 'asset' && (!origin.pair_confirmed || key(origin.audio_path || '') !== key(audio))) {
      stages[stage].issues.push('字幕与本步骤音频共同使用，请在字幕来源处选择对应音频并确认')
    } else if (origin.kind === 'stage' && origin.stage === 'asr' && key(audioOrigin(flow.bindings.asr?.audio)) !== key(audio)) {
      stages[stage].issues.push('识别字幕与本步骤音频来源不同，请选择同一录音')
    }
  }
  for (const stage of STAGES) {
    if (!flow.selectedStages.includes(stage)) continue
    const result = stages[stage]
    for (const port of FLOW_PORTS[stage]) {
      const ref = flow.bindings[stage]?.[port.key]
      if (!ref) { result.issues.push(`请选择${port.label}来源`); continue }
      if (ref.kind === 'stage') {
        result.upstream = true
        if (!flow.selectedStages.includes(ref.stage)) result.issues.push(`${LABELS[ref.stage]}未勾选，请选择步骤或改用素材`)
        else if (!sourceOptions(stage, port.type, flow, []).some(option => option.value === referenceValue(ref))) result.issues.push(`${port.label}不能引用当前或后续步骤（循环／类型不符）`)
        else if (stages[ref.stage].issues.length) result.issues.push(`${LABELS[ref.stage]}缺少必要素材`)
      } else {
        const item = find(ref.path)
        if (!item) { result.issues.push(`${port.label}素材未选中或已移除`); continue }
        if (materialKind(item) !== (port.type === 'text' ? 'subtitle' : 'audio')) result.issues.push(`${port.label}素材类型不符`)
        if (port.type === 'text') {
          const summary = item.subtitleSummary
          if (summary?.valid === false) result.issues.push(`字幕无效：${summary.reason}`)
          if (!known(summary?.language) && (!ref.language || !ref.language_confirmed)) result.issues.push('字幕语言未知，请确认语言')
          if (known(summary?.language) && ref.language_confirmed && language(ref.language) !== language(summary?.language)) result.issues.push('确认语言与字幕检测语言不符')
          if (ref.audio_path && (!find(ref.audio_path) || !ref.pair_confirmed)) result.issues.push('请确认字幕与所选音频的对应关系')
          if (stage === 'align' && !ref.audio_path) result.issues.push('请指定字幕对应音频并确认，运行前将校验时间轴')
        }
      }
      if (port.type === 'text' && (stage === 'tts' || stage === 'translate' || stage === 'align')) {
        const actual = textLanguage(ref)
        const expected = language(stage === 'tts' ? targetLang : sourceLang)
        if (actual && actual !== expected) result.issues.push(stage === 'tts'
          ? '字幕语言与目标语言不同，请提供目标字幕或自行勾选翻译并绑定其产物'
          : '字幕语言与源语言不同，请核对源语言和字幕来源')
      }
    }
  }
  const issues = STAGES.flatMap(id => stages[id].issues.map(issue => `${LABELS[id]}：${issue}`))
  if (!flow.selectedStages.length) issues.push('请在顶部勾选需要执行的步骤')
  if (!flow.outputs.length) issues.push('请至少选择一项产出')
  if (flow.outputs.some(id => !flow.selectedStages.includes(id))) issues.push('产出对应的步骤未勾选')
  return { stages, issues, ready: issues.length === 0 }
}
