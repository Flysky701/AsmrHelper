import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
const source = await readFile(new URL('../src/domain/workbenchFlow.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { emptyFlow, assessFlow, restoreFlow, toggleFlowStage, sourceOptions, workflowPayload, FLOW_PRESETS, applyFlowPreset, matchingFlowPreset } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const audio = { path: 'a.wav', name: 'a.wav', kind: 'audio', companionPaths: [] }
const subtitle = language => ({ path: `${language}.vtt`, name: `${language}.vtt`, kind: 'subtitle', companionPaths: [], subtitleSummary: { language, valid: true, reason: '' } })
const asset = path => ({ kind: 'asset', path })
const stage = stage => ({ kind: 'stage', stage })
const flow = (selectedStages, bindings, outputs = selectedStages.slice(-1)) => ({ ...emptyFlow(), selectedStages, bindings, outputs })

test('four common presets select supported steps; target subtitles only select TTS', () => {
  const expected = [['asr', 'export'], ['translate', 'export'], ['tts'], ['asr', 'translate', 'tts', 'export']]
  FLOW_PRESETS.forEach((preset, index) => {
    const draft = applyFlowPreset(emptyFlow(), preset.id)
    assert.deepEqual(draft.selectedStages, expected[index])
    assert.deepEqual(draft.outputs, expected[index]) // Existing checkbox defaults, not a new output mode.
    assert.deepEqual(draft.bindings, {})
    assert.equal(matchingFlowPreset(draft).id, preset.id)
    assert.equal(assessFlow(draft, [], 'ja', 'zh').ready, false)
  })
  const target = applyFlowPreset(flow([], { tts: { text: asset('zh.vtt') } }), 'subtitle_speech')
  assert.equal(assessFlow(target, [subtitle('zh')], 'ja', 'zh').ready, true)
  assert.deepEqual(workflowPayload(target).outputs, ['tts'])
  assert.equal(assessFlow(target, [subtitle('ja')], 'ja', 'zh').ready, false)
})

test('preset switching preserves bindings, formats and retained output choices; repeated selection is idempotent', () => {
  const original = { ...flow(['translate', 'tts', 'export'], {
    translate: { text: asset('ja.vtt') }, tts: { text: stage('translate') }, export: { text: stage('translate') },
  }, ['tts']), subtitleFormat: 'vtt' }
  const before = structuredClone(original)
  const draft = applyFlowPreset(original, 'audio_subtitles')
  assert.deepEqual(original, before)
  assert.deepEqual(draft.bindings, original.bindings)
  assert.equal(draft.subtitleFormat, 'vtt')
  assert.deepEqual(draft.outputs, ['asr']) // New ASR output defaults on; previously unselected export stays off.
  assert.match(assessFlow(draft, [audio, subtitle('ja')], 'ja', 'zh').issues.join(' '), /未勾选/)
  assert.strictEqual(applyFlowPreset(draft, 'audio_subtitles'), draft)
  const noDelivery = { ...draft, outputs: [] }
  assert.strictEqual(applyFlowPreset(noDelivery, 'audio_subtitles'), noDelivery)
  assert.strictEqual(applyFlowPreset(draft, 'invalid'), draft)
})

test('preset match derives from current steps after edits and restore, without a persisted preset mode', () => {
  const preset = applyFlowPreset(emptyFlow(), 'audio_translation_speech')
  let edited = toggleFlowStage(preset, 'mix')
  assert.equal(matchingFlowPreset(edited), undefined)
  edited = toggleFlowStage(edited, 'mix')
  edited.selectedStages.reverse()
  edited.outputs = ['tts']
  assert.equal(matchingFlowPreset(edited).id, 'audio_translation_speech')
  const restored = restoreFlow(JSON.parse(JSON.stringify(edited)))
  assert.equal(matchingFlowPreset(restored).id, 'audio_translation_speech')
  assert.equal('preset' in restored, false)
})

test('subtitle export, same-language TTS, translated TTS, ASR-only and full flow respect explicit sources', () => {
  const cases = [
    [flow(['export'], { export: { text: asset('zh.vtt') } }), [subtitle('zh')]],
    [flow(['tts'], { tts: { text: asset('zh.vtt') } }), [subtitle('zh')]],
    [flow(['translate', 'tts'], { translate: { text: asset('ja.vtt') }, tts: { text: stage('translate') } }), [subtitle('ja')]],
    [flow(['asr'], { asr: { audio: asset('a.wav') } }), [audio]],
    [flow(['separate', 'asr', 'align', 'translate', 'tts', 'mix', 'export'], {
      separate: { audio: asset('a.wav') }, asr: { audio: stage('separate') }, align: { audio: stage('separate'), text: stage('asr') },
      translate: { text: stage('align') }, tts: { text: stage('translate') }, mix: { audio: asset('a.wav'), speech: stage('tts') }, export: { text: stage('translate') },
    }), [audio]],
  ]
  for (const [draft, materials] of cases) assert.deepEqual(assessFlow(draft, materials, 'ja', 'zh').issues, [])
})

test('foreign-language TTS, unknown language and unpaired mixing require explicit correction', () => {
  const draft = flow(['tts'], { tts: { text: asset('ja.vtt') } })
  assert.match(assessFlow(draft, [subtitle('ja')], 'ja', 'zh').issues.join(' '), /自行勾选翻译/)
  draft.bindings.tts.text = asset('unknown.vtt')
  assert.match(assessFlow(draft, [subtitle('unknown')], 'ja', 'zh').issues.join(' '), /请确认语言/)
  draft.bindings.tts.text = { ...asset('unknown.vtt'), language: 'zh', language_confirmed: true }
  assert.equal(assessFlow(draft, [subtitle('unknown')], 'ja', 'zh').ready, true)
  draft.selectedStages.push('mix'); draft.bindings.mix = { audio: asset('a.wav'), speech: stage('tts') }
  assert.match(assessFlow(draft, [audio, subtitle('unknown')], 'ja', 'zh').issues.join(' '), /对应音频并确认/)
  Object.assign(draft.bindings.tts.text, { audio_path: 'a.wav', pair_confirmed: true })
  assert.equal(assessFlow(draft, [audio, subtitle('unknown')], 'ja', 'zh').ready, true)
  const mismatch = flow(['align'], { align: { audio: asset('a.wav'), text: { ...asset('zh.vtt'), audio_path: 'a.wav', pair_confirmed: true } } })
  assert.match(assessFlow(mismatch, [audio, subtitle('zh')], 'ja', 'zh').issues.join(' '), /与源语言不同/)
})

test('multiple candidates stay unbound; removing upstream or material reports missing source without fallback', () => {
  let draft = flow(['translate', 'tts'], { translate: { text: asset('ja.vtt') }, tts: { text: stage('translate') } })
  assert.equal(sourceOptions('translate', 'text', draft, [subtitle('ja'), subtitle('zh')]).length, 2)
  assert.equal(assessFlow(flow(['tts'], {}), [subtitle('zh')], 'ja', 'zh').ready, false)
  draft = toggleFlowStage(draft, 'translate')
  assert.deepEqual(draft.bindings.tts.text, stage('translate'))
  assert.match(assessFlow(draft, [subtitle('ja')], 'ja', 'zh').issues.join(' '), /未勾选/)
  assert.equal(assessFlow(flow(['tts'], { tts: { text: asset('zh.vtt') } }), [], 'ja', 'zh').ready, false)
})

test('cycles and missing delivery are visible; saved outputs restore without reviving old modes', () => {
  const draft = flow(['translate', 'tts'], { translate: { text: stage('tts') }, tts: { text: stage('translate') } }, [])
  assert.match(assessFlow(draft, [], 'ja', 'zh').issues.join(' '), /循环/)
  assert.match(assessFlow(draft, [], 'ja', 'zh').issues.join(' '), /至少选择一项产出/)
  draft.outputs = ['tts']; draft.subtitleFormat = 'vtt'
  const restored = restoreFlow(JSON.parse(JSON.stringify(draft)))
  assert.deepEqual(restored, draft)
  restored.bindings.tts.text = asset('changed.vtt')
  assert.deepEqual(draft.bindings.tts.text, stage('translate'))
  assert.deepEqual(restoreFlow({ subtitleInputMode: 'direct_tts', useVocalSeparator: true }), emptyFlow())
  assert.equal(workflowPayload(toggleFlowStage(restored, 'translate')).bindings.translate, undefined)
})
