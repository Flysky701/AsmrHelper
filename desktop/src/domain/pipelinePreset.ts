import type { GraphPresetItem, PresetItem } from '../api/types'
import type { GraphNodeKind } from './workflowGraph'

export const PIPELINE_STAGE_IDS = [
  'separate',
  'asr',
  'align',
  'translate',
  'tts',
  'mix',
  'export',
] as const

export type PipelineStageId = (typeof PIPELINE_STAGE_IDS)[number]

export const PIPELINE_STAGE_LABELS: Record<PipelineStageId, string> = {
  separate: '人声分离',
  asr: '语音识别',
  align: '时间轴校准',
  translate: '字幕翻译',
  tts: '语音合成',
  mix: '混音输出',
  export: '字幕导出',
}

const STAGE_ALIASES: Record<string, PipelineStageId> = {
  separation: 'separate',
  separate: 'separate',
  asr: 'asr',
  align: 'align',
  translation: 'translate',
  translate: 'translate',
  tts: 'tts',
  mix: 'mix',
  export: 'export',
}

export function normalizePresetStages(stages: string[]): Set<PipelineStageId> {
  return new Set(
    stages.flatMap((stage) => {
      const normalized = STAGE_ALIASES[stage]
      return normalized ? [normalized] : []
    }),
  )
}

const PRESET_CATEGORIES = [
  '字幕直接配音',
  '字幕配音与混音',
  '字幕翻译配音',
  '录音转写配音',
  '录音翻译配音',
  '录音转字幕',
  '字幕翻译',
  '字幕校准与导出',
  '音频分离与提取',
  '混音与音频导出',
  '其他流水线',
] as const

type PresetCategory = (typeof PRESET_CATEGORIES)[number]
type WorkflowPreset = GraphPresetItem | PresetItem

function presetCategory(preset: WorkflowPreset): PresetCategory {
  const stages = 'graph' in preset
    ? new Set<GraphNodeKind>(preset.graph.nodes.map(node => node.kind))
    : new Set<GraphNodeKind>(normalizePresetStages(preset.stages))

  if (stages.has('tts')) {
    if (stages.has('asr')) return stages.has('translate') ? '录音翻译配音' : '录音转写配音'
    if (stages.has('translate')) return '字幕翻译配音'
    return stages.has('mix') ? '字幕配音与混音' : '字幕直接配音'
  }
  if (stages.has('asr')) return '录音转字幕'
  if (stages.has('translate')) return '字幕翻译'
  if (stages.has('align') || stages.has('export')) return '字幕校准与导出'
  if (stages.has('mix') || stages.has('audio_export')) return '混音与音频导出'
  if (stages.has('separate') || stages.has('audio_difference')) return '音频分离与提取'
  return '其他流水线'
}

export function groupWorkflowPresets<T extends WorkflowPreset>(presets: readonly T[]) {
  const groups = new Map<PresetCategory, T[]>(PRESET_CATEGORIES.map(label => [label, []]))
  for (const preset of presets) groups.get(presetCategory(preset))?.push(preset)
  return [...groups].filter(([, items]) => items.length > 0).map(([label, items]) => ({ label, items }))
}
