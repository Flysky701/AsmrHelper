export const PIPELINE_STAGE_IDS = [
  'separate',
  'asr',
  'translate',
  'tts',
  'mix',
  'export',
] as const

export type PipelineStageId = (typeof PIPELINE_STAGE_IDS)[number]

export const PIPELINE_STAGE_LABELS: Record<PipelineStageId, string> = {
  separate: '人声分离',
  asr: '语音识别',
  translate: '字幕翻译',
  tts: '语音合成',
  mix: '混音输出',
  export: '字幕导出',
}

const STAGE_ALIASES: Record<string, PipelineStageId> = {
  separation: 'separate',
  separate: 'separate',
  asr: 'asr',
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
