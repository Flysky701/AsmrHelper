import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/domain/pipelineExecutionProfile.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { buildPipelineExecutionProfile } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

function input(tts = true) {
  return {
    params: { sourceLang: 'ja', targetLang: 'zh', translateModel: '', skipExisting: false },
    stageFlags: { separate: false, asr: false, align: false, translate: false, tts, mix: true, export: true },
    capabilities: [], capabilityOptions: {}, speechStage: null,
  }
}

test('resolved Speech stage is the sole TTS source and detached from the editable draft', () => {
  const stage = {
    enabled: true, provider: 'fish_audio', model: 'selected-model',
    options: { speech_source: { connection_ref: 'saved-service', variant: { kind: 'hosted', value: 'voice-id' } } },
    provider_options: {},
  }
  const args = { ...input(), speechStage: stage,
    capabilities: [{ category: 'tts', provider: 'fish_audio', default_model: 'stale-legacy-model' }] }
  const profile = buildPipelineExecutionProfile(args)
  assert.deepEqual(profile.stages.tts, stage)
  stage.options.speech_source.variant.value = 'edited-after-submit'
  assert.equal(profile.stages.tts.options.speech_source.variant.value, 'voice-id')
})

test('enabled TTS cannot silently fall back to a legacy default', () => {
  assert.throws(() => buildPipelineExecutionProfile(input()), /配音引擎配置/)
  assert.throws(() => buildPipelineExecutionProfile({ ...input(), speechStage: { enabled: false } }), /配音引擎配置/)
})

test('non-speech presets need no Speech selection and carry no stale voice configuration', () => {
  const profile = buildPipelineExecutionProfile({ ...input(false), speechStage: { enabled: true, provider: 'stale' } })
  assert.deepEqual(profile.stages.tts, { enabled: false, provider: 'speech', model: null, options: {}, provider_options: {} })
  assert.equal(profile.stages.mix.enabled, true)
})
