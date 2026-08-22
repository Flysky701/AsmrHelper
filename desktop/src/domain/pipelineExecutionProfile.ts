import type {
  CapabilityDescriptorResponse,
  PipelineExecutionProfileRequest,
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
  params: WorkbenchParams,
): PipelineStageFlags {
  return {
    separate: activeStages.has('separate') && params.useVocalSeparator,
    asr: activeStages.has('asr'),
    translate: activeStages.has('translate') && params.sourceLang !== params.targetLang,
    tts: activeStages.has('tts'),
    mix: activeStages.has('mix'),
    export: activeStages.has('export'),
  }
}

export function buildPipelineExecutionProfile({
  params,
  stageFlags,
  capabilities,
  capabilityOptions,
}: {
  params: WorkbenchParams
  stageFlags: PipelineStageFlags
  capabilities: CapabilityDescriptorResponse[]
  capabilityOptions: Record<string, Record<string, unknown>>
}): PipelineExecutionProfileRequest {
  const asrDescriptor = capabilities.find(
    (item) => item.category === 'asr' && item.provider === params.asrProvider,
  )
  const llmDescriptor = capabilities.find(
    (item) => item.category === 'llm' && item.provider === params.translateProvider,
  )
  const ttsDescriptor = capabilities.find(
    (item) => item.category === 'tts' && item.provider === params.ttsEngine,
  )
  const asrProviderOptions = stageFlags.asr
    ? optionPayload(asrDescriptor, 'provider', capabilityOptions)
    : {}
  const llmCommonOptions = stageFlags.translate
    ? optionPayload(llmDescriptor, 'common', capabilityOptions)
    : {}
  const ttsProviderOptions = stageFlags.tts
    ? optionPayload(ttsDescriptor, 'provider', capabilityOptions)
    : {}
  if (params.voiceProfileId) {
    ttsProviderOptions.voice_profile_id = params.voiceProfileId
  } else {
    delete ttsProviderOptions.voice_profile_id
  }

  return {
    version: 1,
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
      translate: {
        enabled: stageFlags.translate,
        provider: params.translateProvider,
        model: params.translateModel || llmDescriptor?.default_model || null,
        options: {
          source_lang: params.sourceLang,
          target_lang: params.targetLang,
          preserve_timestamps: true,
          ...llmCommonOptions,
        },
        provider_options: {},
      },
      tts: {
        enabled: stageFlags.tts,
        provider: params.ttsEngine,
        model: ttsDescriptor?.default_model || null,
        options: {
          voice: params.ttsVoice,
          speed: params.ttsSpeed,
          language: params.targetLang,
        },
        provider_options: ttsProviderOptions,
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
          subtitle_format: 'srt',
          include_intermediate_files: true,
        },
        provider_options: {},
      },
    },
  }
}
