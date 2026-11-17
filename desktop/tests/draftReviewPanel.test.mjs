import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)

class MockApiError extends Error {
  constructor(code, message, status) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

function createMockClient({ onGet, onPost } = {}) {
  const API_BASE = 'http://127.0.0.1:8000/api/v1'
  const apiUrl = (path) => `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
  return {
    DEFAULT_API_BASE: API_BASE,
    API_BASE,
    ApiError: MockApiError,
    apiUrl,
    api: {
      get: async (path) => (onGet ? onGet(path) : undefined),
      post: async (path, body) => (onPost ? onPost(path, body) : undefined),
      put: async () => undefined,
      delete: async () => undefined,
    },
  }
}

const zhI18n = {
  t: (value) => value,
  useI18n: () => (value) => value,
  format: (source, values) => source.replace(/\{(\d+)\}/g, (_, idx) => String(values[Number(idx)] ?? '')),
}

function load(relative, overrides = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  })
  const mod = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(
    (name) => {
      if (name in overrides) return overrides[name]
      if (name === '@/i18n') return zhI18n
      if (name === '@/utils/displayPath') return load('../src/utils/displayPath.ts')
      if (name.endsWith('.css')) return {}
      return require(name)
    },
    mod,
    mod.exports,
  )
  return mod.exports
}

function makeDraftFixture() {
  return {
    draft_id: 'draft-rj1001',
    state: 'awaiting_review',
    work_dir: 'D:/Works/RJ1001',
    title: 'RJ1001 朝のお耳かき',
    revision: 3,
    created_at: '2026-11-17T10:00:00Z',
    updated_at: '2026-11-17T10:05:00Z',
    tracks: [
      {
        track_id: 'track-01',
        stem: '01_morning',
        path: 'D:/Works/RJ1001/01_morning.wav',
        duration: 60.0,
      },
    ],
    segments: [
      { index: 0, cue_id: 'cue-0001', start: 0.5, end: 2.8, source_text: 'おはようございます', translation: '早上好呀' },
      { index: 1, cue_id: 'cue-0002', start: 3.2, end: 5.5, source_text: 'よく眠れましたか？', translation: '' },
      { index: 2, cue_id: 'cue-0003', start: 6.0, end: 8.4, source_text: 'ゆっくり休んでね', translation: '好好休息ね' },
      { index: 3, cue_id: 'cue-0004', start: 9.0, end: 10.2, source_text: '大好きだよ', translation: '真的超级超级非常喜欢你呀永远在一起吧' },
      { index: 4, cue_id: 'cue-0005', start: 11.0, end: 12.0, source_text: '♪', translation: '' },
    ],
    voice_plan: { source_lang: 'ja', target_lang: 'zh', chars_per_second: 4.2, max_atempo: 1.35 },
    audit_report: {
      untranslated_indices: [1],
      japanese_residue_indices: [2],
      empty_or_symbol_indices: [4],
      over_speed_cues: [
        {
          index: 3,
          cue_id: 'cue-0004',
          start: 9.0,
          end: 10.2,
          cue_duration: 1.2,
          available_slack: 0.35,
          effective_slot: 1.55,
          char_count: 18,
          estimated_duration: 2.39,
          predicted_atempo: 1.54,
          max_recommended_chars: 11,
          source_text: '大好きだよ',
          translation: '真的超级超级非常喜欢你呀永远在一起吧',
        },
      ],
      summary_counts: {
        total_cues: 5,
        translated_cues: 3,
        untranslated_count: 1,
        japanese_residue_count: 1,
        empty_or_symbol_count: 1,
        over_speed_count: 1,
      },
      gate_passed: false,
      chars_per_second: 4.2,
      max_atempo: 1.35,
      reference_quality: {
        path: 'D:/Works/RJ1001/_staging/voice_reference_candidate.wav',
        duration: 8.0,
        snr_db: 24.6,
      },
      warnings: ['存在 1 句语速超限，建议精简译文字数。'],
    },
    artifacts: {
      primary_track_path: 'D:/Works/RJ1001/01_morning.wav',
      reference_candidate: {
        path: 'D:/Works/RJ1001/_staging/voice_reference_candidate.wav',
        duration: 8.0,
        snr_db: 24.6,
      },
      sample_takes: [
        {
          index: 0,
          cue_id: 'cue-0001',
          text: '早上好呀',
          audio_path: 'D:/Works/RJ1001/_staging/sample_01.wav',
          duration: 1.1,
          take_id: 'take-sample-01',
        },
      ],
    },
  }
}

function loadDraftReviewModule(customOverrides = {}) {
  const client = createMockClient()
  const { useAudioPlayerStore } = load('../src/stores/audioPlayerStore.ts')
  return {
    useAudioPlayerStore,
    panelModule: load('../src/components/tasks/DraftReviewPanel.tsx', {
      '@/api/client': client,
      '@/api/drafts': { draftsApi: {} },
      '@/stores/audioPlayerStore': { useAudioPlayerStore },
      ...customOverrides,
    }),
  }
}

test('warning collection and filterReviewSegments isolate actionable warnings without flagging non-speech symbols', () => {
  const { panelModule } = loadDraftReviewModule()
  const draft = makeDraftFixture()
  const audit = panelModule.normalizeAuditReport(draft.audit_report)
  const warnings = panelModule.collectSegmentWarnings(draft.segments, audit)

  assert.equal(warnings.get(0).hasWarning, false)
  assert.equal(warnings.get(1).untranslated, true)
  assert.equal(warnings.get(2).japaneseResidue, true)
  assert.equal(warnings.get(3).overSpeed?.predicted_atempo, 1.54)
  assert.equal(warnings.get(3).overSpeed?.available_slack, 0.35)
  // Cue 4 is a pure musical symbol "♪" without speakable source text, so it must not be flagged as a blocking warning
  assert.equal(warnings.get(4).blockingEmpty, false)
  assert.equal(warnings.get(4).hasWarning, false)

  const allCues = panelModule.filterReviewSegments(draft.segments, warnings, 'all')
  const warningOnlyCues = panelModule.filterReviewSegments(draft.segments, warnings, 'warnings')
  assert.equal(allCues.length, 5)
  assert.deepEqual(warningOnlyCues.map((c) => c.index), [1, 2, 3])
})

test('buildDraftPatchRequest emits minimal cue diffs with expected_revision', () => {
  const { panelModule } = loadDraftReviewModule()
  const draft = makeDraftFixture()
  const patch = panelModule.buildDraftPatchRequest(
    draft.segments,
    {
      0: '早上好呀', // unchanged from seg.translation -> omitted
      1: '睡得好吗？',
      2: '好好休息吧',
      3: '最喜欢你啦',
    },
    draft.revision,
  )

  assert.equal(patch.expected_revision, 3)
  assert.deepEqual(patch.edits, [
    { index: 1, cue_id: 'cue-0002', translation: '睡得好吗？' },
    { index: 2, cue_id: 'cue-0003', translation: '好好休息吧' },
    { index: 3, cue_id: 'cue-0004', translation: '最喜欢你啦' },
  ])
})

test('DraftReviewPanel renders warning badges before patch and updates gate status after patch transition', () => {
  const { panelModule } = loadDraftReviewModule()
  const Panel = panelModule.default
  const initialDraft = makeDraftFixture()

  const htmlBefore = renderToStaticMarkup(
    React.createElement(Panel, {
      initialDrafts: [initialDraft],
      initialFilter: 'warnings',
      initialEdits: { 1: '睡得好吗？' },
    }),
  )
  assert.match(htmlBefore, /待确认门禁/)
  assert.match(htmlBefore, /⚠ 待人工复核门禁/)
  assert.match(htmlBefore, /data-metric="untranslated">1</)
  assert.match(htmlBefore, /data-metric="japanese-residue">1</)
  assert.match(htmlBefore, /data-metric="over-speed">1</)
  assert.match(htmlBefore, /预计倍速 1\.54x/)
  assert.match(htmlBefore, /借静默 \+0\.35s/)
  assert.match(htmlBefore, /建议 ≤11 字/)
  assert.match(htmlBefore, /待保存 1 处修改/)
  // Warnings-only filter hides normal cue #1 and symbol cue #5
  assert.doesNotMatch(htmlBefore, /おはようございます/)
  assert.match(htmlBefore, /よく眠れましたか？/)

  const patchedDraft = {
    ...initialDraft,
    revision: 4,
    updated_at: '2026-11-17T10:08:00Z',
    segments: initialDraft.segments.map((seg) => {
      if (seg.index === 1) return { ...seg, translation: '睡得好吗？' }
      if (seg.index === 2) return { ...seg, translation: '好好休息吧' }
      if (seg.index === 3) return { ...seg, translation: '最喜欢你啦' }
      return seg
    }),
  }
  const refreshedAudit = {
    untranslated_indices: [],
    japanese_residue_indices: [],
    empty_or_symbol_indices: [4],
    over_speed_cues: [],
    summary_counts: {
      total_cues: 5,
      translated_cues: 4,
      untranslated_count: 0,
      japanese_residue_count: 0,
      empty_or_symbol_count: 1,
      over_speed_count: 0,
    },
    gate_passed: true,
    chars_per_second: 4.2,
    max_atempo: 1.35,
    reference_quality: initialDraft.audit_report.reference_quality,
    warnings: [],
  }

  const nextDrafts = panelModule.applyPatchedDraftState([initialDraft], patchedDraft, refreshedAudit)
  const htmlAfter = renderToStaticMarkup(
    React.createElement(Panel, {
      initialDrafts: nextDrafts,
      initialFilter: 'all',
    }),
  )
  assert.match(htmlAfter, /✓ 质检门禁已通过/)
  assert.match(htmlAfter, /版本 r4/)
  assert.match(htmlAfter, /data-metric="untranslated">0</)
  assert.match(htmlAfter, /data-metric="japanese-residue">0</)
  assert.match(htmlAfter, /data-metric="over-speed">0</)
  assert.doesNotMatch(htmlAfter, /预计倍速/)
})

test('audition helpers wire reference_candidate and sample_takes to AudioPlayerBar store', () => {
  const { panelModule, useAudioPlayerStore } = loadDraftReviewModule()
  const draft = makeDraftFixture()
  const audit = panelModule.normalizeAuditReport(draft.audit_report)

  const refCandidate = panelModule.getReferenceCandidate(draft, audit)
  assert.equal(refCandidate.path, 'D:/Works/RJ1001/_staging/voice_reference_candidate.wav')

  const takes = panelModule.getSampleTakes(draft)
  assert.equal(takes.length, 1)
  assert.equal(
    panelModule.resolveSampleTakeAudioSrc(takes[0]),
    'http://127.0.0.1:8000/api/v1/speech/takes/take-sample-01/audio',
  )
  assert.equal(
    panelModule.resolveSampleTakeAudioSrc({ ...takes[0], take_id: undefined }),
    'D:/Works/RJ1001/_staging/sample_01.wav',
  )

  const store = useAudioPlayerStore.getState()
  panelModule.playClipInAudioBar(store, refCandidate.path, 'RJ1001 · 克隆参考干声')
  assert.equal(useAudioPlayerStore.getState().visible, true)
  assert.equal(useAudioPlayerStore.getState().src, refCandidate.path)
  assert.equal(useAudioPlayerStore.getState().title, 'RJ1001 · 克隆参考干声')
  assert.equal(useAudioPlayerStore.getState().isPlaying, true)
  useAudioPlayerStore.getState().hide()
})

test('commit payload construction and draftsApi endpoints follow FastAPI schemas and 409 conflict contract', async () => {
  const { panelModule } = loadDraftReviewModule()
  assert.equal(panelModule.defaultCommitOutputDir('D:/Works/RJ1001/'), 'D:/Works/RJ1001/output')
  assert.equal(panelModule.defaultCommitOutputDir('D:\\Works\\RJ1001\\'), 'D:\\Works\\RJ1001/output')

  const commitBody = panelModule.buildDraftCommitRequest({
    outputDir: '  D:/Works/RJ1001/output  ',
    exportSrt: true,
    exportLrc: true,
    bilingual: true,
    enableDubbing: false,
    expectedRevision: 4,
  })
  assert.deepEqual(commitBody, {
    output_dir: 'D:/Works/RJ1001/output',
    export_formats: ['srt', 'lrc'],
    enable_dubbing: false,
    bilingual: true,
    expected_revision: 4,
  })

  const getCalls = []
  const postCalls = []
  const mockClient = createMockClient({
    onGet: async (path) => {
      getCalls.push(path)
      return { ok: true, path }
    },
    onPost: async (path, body) => {
      postCalls.push({ path, body })
      return { draft_id: 'draft-rj1001', state: 'completed', ...body }
    },
  })

  const { draftsApi } = load('../src/api/drafts.ts', {
    './client': mockClient,
  })

  await draftsApi.list({ state: 'awaiting_review', limit: 25 })
  await draftsApi.get('draft/rj1001')
  await draftsApi.getAudit('draft/rj1001')
  assert.deepEqual(getCalls, [
    '/drafts?state=awaiting_review&limit=25',
    '/drafts/draft%2Frj1001',
    '/drafts/draft%2Frj1001/audit',
  ])

  const commitResp = await draftsApi.commit('draft-rj1001', commitBody)
  assert.equal(commitResp.state, 'completed')
  assert.deepEqual(postCalls, [{ path: '/drafts/draft-rj1001/commit', body: commitBody }])

  const originalFetch = globalThis.fetch
  const patchCalls = []
  try {
    globalThis.fetch = async (url, init) => {
      patchCalls.push({ url, method: init.method, body: JSON.parse(init.body) })
      return {
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ draft_id: 'draft-rj1001', revision: 4, state: 'awaiting_review' }),
      }
    }
    const patched = await draftsApi.patch('draft-rj1001', {
      edits: [{ index: 1, translation: '睡得好吗？' }],
      expected_revision: 3,
    })
    assert.equal(patched.revision, 4)
    assert.equal(patchCalls[0].method, 'PATCH')
    assert.equal(patchCalls[0].url, 'http://127.0.0.1:8000/api/v1/drafts/draft-rj1001')

    globalThis.fetch = async () => ({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({ error: { code: 'REVISION_CONFLICT', message: 'expected 3, current 4' } }),
    })
    await assert.rejects(
      () => draftsApi.patch('draft-rj1001', { edits: [], expected_revision: 3 }),
      (err) => err.code === 'REVISION_CONFLICT' && err.status === 409,
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Draft Gate i18n translates all UI controls into English and TaskCenter mounts the drafts tab', () => {
  let language = 'en'
  const { en } = load('../src/locales/en.ts')
  const realI18n = load('../src/i18n.ts', {
    './locales/en': { en },
    ...Object.fromEntries(
      ['workflow', 'voices', 'operations', 'shared', 'audio', 'help'].map((name) => [
        `./locales/${name}`,
        load(`../src/locales/${name}.ts`),
      ]),
    ),
    './stores/appearanceStore': { useAppearanceStore: { getState: () => ({ language }) } },
  })
  realI18n.useI18n = () => realI18n.t

  assert.equal(realI18n.t('待审草稿'), 'Draft Gate')
  assert.equal(realI18n.t('待确认门禁'), 'Awaiting Review')
  assert.equal(realI18n.t('仅看预警项'), 'Warnings Only')
  assert.equal(realI18n.t('保存修订'), 'Save Edits')
  assert.equal(realI18n.t('确认合成并交付'), 'Approve & Render')
  assert.equal(realI18n.t('启用配音混音'), 'Enable Dubbing')

  const { panelModule } = loadDraftReviewModule({
    '@/i18n': realI18n,
  })
  const asciiDraft = {
    ...makeDraftFixture(),
    title: 'RJ1001 Morning Track',
    segments: [
      { index: 0, cue_id: 'cue-0001', start: 0.5, end: 2.8, source_text: 'Ohayou', translation: 'Good morning' },
      { index: 1, cue_id: 'cue-0002', start: 3.2, end: 5.5, source_text: 'Oyasumi', translation: '' },
      { index: 3, cue_id: 'cue-0004', start: 9.0, end: 10.2, source_text: 'Daisuki', translation: 'Love you forever and ever' },
    ],
    audit_report: {
      ...makeDraftFixture().audit_report,
      warnings: [],
    },
    artifacts: {
      ...makeDraftFixture().artifacts,
      sample_takes: [
        {
          index: 0,
          cue_id: 'cue-0001',
          text: 'Good morning',
          audio_path: 'D:/Works/RJ1001/_staging/sample_01.wav',
          duration: 1.1,
          take_id: 'take-sample-01',
        },
      ],
    },
  }
  const englishHtml = renderToStaticMarkup(
    React.createElement(panelModule.default, {
      initialDrafts: [asciiDraft],
      initialEdits: { 1: 'Good night' },
    }),
  )
  assert.match(englishHtml, /Awaiting Review/)
  assert.match(englishHtml, /Warnings Only/)
  assert.match(englishHtml, /Save Edits/)
  assert.match(englishHtml, /Approve &amp; Render/)
  assert.match(englishHtml, /Enable Dubbing/)
  assert.match(englishHtml, /Audition Voice Ref/)
  assert.match(englishHtml, /D:\/Works\/RJ1001\/output/)
  assert.doesNotMatch(englishHtml, /[\u4e00-\u9fff]/)

  const completedAsciiHtml = renderToStaticMarkup(
    React.createElement(panelModule.default, {
      initialDrafts: [
        {
          ...asciiDraft,
          state: 'completed',
          audit_report: { ...asciiDraft.audit_report, gate_passed: true, untranslated_indices: [], japanese_residue_indices: [], over_speed_cues: [] },
          artifacts: {
            ...asciiDraft.artifacts,
            output_dir: 'D:/Works/RJ1001/output',
            subtitles: { srt: 'D:/Works/RJ1001/output/01_morning.srt', lrc: 'D:/Works/RJ1001/output/01_morning.lrc' },
            mixed_audio_path: 'D:/Works/RJ1001/output/01_morning_dubbed.wav',
            dubbing: {
              mixed_audio_path: 'D:/Works/RJ1001/output/01_morning_dubbed.wav',
              reused_take_count: 2,
              synthesized_take_count: 1,
            },
          },
        },
      ],
    }),
  )
  assert.match(completedAsciiHtml, /Re-render &amp; Deliver/)
  assert.match(completedAsciiHtml, /Delivered Artifacts/)
  assert.doesNotMatch(completedAsciiHtml, /[\u4e00-\u9fff]/)

  const taskCenterSource = readFileSync(new URL('../src/pages/TaskCenter.tsx', import.meta.url), 'utf8')
  assert.match(taskCenterSource, /setTaskCenterView\('drafts'\)/)
  assert.match(taskCenterSource, /<DraftReviewPanel\s*\/>/)
})
