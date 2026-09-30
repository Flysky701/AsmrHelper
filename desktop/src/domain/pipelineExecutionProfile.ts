import type {
  CapabilityDescriptorResponse,
  PipelineExecutionProfileRequest,
  PipelineWorkflowRequest,
  StageProfileRequest,
} from '@/api/types'
import type { PipelineStageId } from '@/domain/pipelinePreset'
import type { WorkbenchParams } from '@/stores/workbenchStore'

export type PipelineStageFlags = Record<PipelineStageId, boolean>

export function capabilityScope(
  category: string,
  provider: string,
  schema: 'common' | 'provider',
) {
  return `${category}/${provider}/${schema}`
}

function optionPayload(
  descriptor: CapabilityDescriptorResponse | undefined,
  schema: 'common' | 'provider',
  values: Record<string, Record<string, unknown>>,
) {
  if (!descriptor) return {}
  const scope = capabilityScope(descriptor.category, descriptor.provider, schema)
  const current = values[scope] ?? {}
  const definitions = schema === 'common'
    ? descriptor.common_option_schema
    : descriptor.provider_option_schema

  return Object.fromEntries(
    definitions.flatMap((option) => {
      const value = current[option.name] ?? option.default
      return value === null || value === undefined || value === ''
        ? []
        : [[option.name, value]]
    }),
  )
}

export function buildPipelineStageFlags(
  activeStages: Set<PipelineStageId>,
): PipelineStageFlags {
  return {
    separate: activeStages.has('separate'), asr: activeStages.has('asr'), align: activeStages.has('align'),
    translate: activeStages.has('translate'), tts: activeStages.has('tts'), mix: activeStages.has('mix'),
    export: activeStages.has('export'),
  }
}

export function buildPipelineExecutionProfile({
  params,
  stageFlags,
  capabilities,
  capabilityOptions,
  speechStage,
  workflow,
  subtitleFormat = 'srt',
}: {
  params: WorkbenchParams
  stageFlags: PipelineStageFlags
  capabilities: CapabilityDescriptorResponse[]
  capabilityOptions: Record<string, Record<string, unknown>>
  speechStage: StageProfileRequest | null
  workflow?: PipelineWorkflowRequest
  subtitleFormat?: 'srt' | 'vtt'
}): PipelineExecutionProfileRequest {
  if (stageFlags.tts && !speechStage?.enabled) {
    throw new Error('请先完成配音引擎配置')
  }
  const asrDescriptor = capabilities.find(
    (item) => item.category === 'asr' && item.provider === params.asrProvider,
  )
  const llmDescriptor = capabilities.find(
    (item) => item.category === 'llm' && item.provider === params.translateProvider,
  )
  const asrProviderOptions = stageFlags.asr
    ? optionPayload(asrDescriptor, 'provider', capabilityOptions)
    : {}
  const llmCommonOptions = stageFlags.translate
    ? optionPayload(llmDescriptor, 'common', capabilityOptions)
    : {}

  return {
    version: 1,
    ...(workflow ? { workflow: structuredClone(workflow) } : {}),
    source_lang: params.sourceLang,
    target_lang: params.targetLang,
    skip_existing: params.skipExisting,
    stages: {
      separate: {
        enabled: stageFlags.separate,
        provider: params.vocalProvider,
        model: params.vocalModel,
        options: { mode: 'vocals' },
        provider_options: {},
      },
      asr: {
        enabled: stageFlags.asr,
        provider: params.asrProvider,
        model: params.asrModel,
        options: {
          language: params.sourceLang,
          output_format: 'segments',
          timestamps: true,
        },
        provider_options: asrProviderOptions,
      },
      align: {
        enabled: stageFlags.align,
        provider: 'qwen3_forced_aligner',
        model: 'qwen3-forced-aligner-0.6b',
        options: {},
        provider_options: {},
      },
      translate: {
        enabled: stageFlags.translate,
        provider: params.translateProvider,
        model: params.translateModel.trim() || (params.translateConnectionId ? null : llmDescriptor?.default_model || null),
        options: {
          source_lang: params.sourceLang,
          target_lang: params.targetLang,
          preserve_timestamps: true,
          ...llmCommonOptions,
          ...(params.translateConnectionId ? { connection_ref: params.translateConnectionId } : {}),
        },
        provider_options: {},
      },
      tts: stageFlags.tts && speechStage ? structuredClone(speechStage) : {
        enabled: false,
        provider: 'speech',
        model: null,
        options: {},
        provider_options: {},
      },
      mix: {
        enabled: stageFlags.mix,
        provider: 'ffmpeg',
        model: null,
        options: {
          original_volume: params.originalVolume,
          tts_volume_ratio: params.ttsVolumeRatio,
          tts_delay_ms: params.ttsDelay * 1000,
          normalize: true,
        },
        provider_options: {},
      },
      export: {
        enabled: stageFlags.export,
        provider: 'ffmpeg',
        model: null,
        options: {
          subtitle_format: subtitleFormat,
          include_intermediate_files: true,
        },
        provider_options: {},
      },
    },
  }
}
