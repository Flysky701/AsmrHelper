import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
const source = await readFile(new URL('../src/domain/pipelineExecutionProfile.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { buildPipelineStageFlags, buildPipelineExecutionProfile } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('only checked stages execute; old reuse mode and matching languages cannot alter the selection', () => {
  const params = { sourceLang: 'zh', targetLang: 'zh', translateModel: '', useVocalSeparator: true,
    alignSubtitles: true, reuseTranslations: true, subtitleInputMode: 'direct_tts' }
  const stageFlags = buildPipelineStageFlags(new Set(['translate', 'export']), params)
  assert.deepEqual(stageFlags, { separate: false, asr: false, align: false, translate: true, tts: false, mix: false, export: true })
  const workflow = { version: 1, bindings: { translate: { text: { kind: 'asset', path: 'a.vtt' } } }, outputs: ['export'] }
  const profile = buildPipelineExecutionProfile({ params, stageFlags, capabilities: [], capabilityOptions: {}, speechStage: null, workflow, subtitleFormat: 'vtt' })
  assert.equal(profile.stages.translate.options.direct_tts, undefined)
  assert.equal(profile.stages.translate.options.reuse_existing, undefined)
  assert.equal(profile.stages.export.options.subtitle_format, 'vtt')
  assert.deepEqual(profile.workflow, workflow)
  workflow.bindings.translate.text.path = 'edited.vtt'
  assert.equal(profile.workflow.bindings.translate.text.path, 'a.vtt')
})
