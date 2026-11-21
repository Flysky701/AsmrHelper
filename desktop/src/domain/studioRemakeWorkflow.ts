import type { GraphPresetDraft } from '@/api/types'
import { emptyGraph, newGraphNode } from './workflowDraft'
import type { GraphLanguage, GraphNode, GraphNodeKind, GraphSource } from './workflowGraph'

export type StudioScenario = 'binaural_dub' | 'subtitle' | 'script_dub'
export type RemakeTier = 'fast' | 'asmr' | 'studio'

export const REMAKE_TIERS = {
  fast: {
    label: '快速',
    summary: '静态声像 · FFmpeg 变速 · 跳过验卡',
    options: { borrow_silence_slack: false, acoustic_options: {
      binaural_mode: 'static', loudness_match: 'global', time_stretch_engine: 'ffmpeg_atempo',
    } },
  },
  asmr: {
    label: 'ASMR 精制',
    summary: '动态 HRTF 双耳 · 自动耳语识别 · 句尾借时 · 逐句响度',
    options: { borrow_silence_slack: true, acoustic_options: {
      binaural_mode: 'dynamic_hrtf', loudness_match: 'per_cue', time_stretch_engine: 'pytsmod_wsola',
    } },
  },
  studio: {
    label: '极致原声',
    summary: '在精制基础上开启 EQ 频响匹配 · 近场混响 · Whisper 验卡',
    options: { borrow_silence_slack: true, verify_with_asr: true, max_retries: 2, min_similarity: .75, acoustic_options: {
      binaural_mode: 'dynamic_hrtf', loudness_match: 'per_cue', time_stretch_engine: 'pytsmod_wsola',
      eq_matching: true, eq_strength: .5, reverb_match: true,
    } },
  },
} satisfies Record<RemakeTier, { label: string; summary: string; options: GraphNode['options'] }>

interface StudioWorkflowOptions {
  scenario: StudioScenario
  tier: RemakeTier
  sourceLang: GraphLanguage
  targetLang: GraphLanguage
  subtitleInput: boolean
  separationModel: string
  durationAware: boolean
  translationConnection?: { id: string; provider: string; model?: string }
  recipeId: string
  enableSeedVc: boolean
}

export function studioWorkflow(input: StudioWorkflowOptions): GraphPresetDraft {
  const graph = emptyGraph()
  const audio: GraphSource = { kind: 'slot', slot_id: 'audio_1' }
  const source = (node: GraphNode, port: string): GraphSource => ({ kind: 'node', node_id: node.id, port })
  const add = (kind: GraphNodeKind, inputs: Record<string, GraphSource>, settings: Partial<GraphNode> = {}) => {
    const node = { ...newGraphNode(kind, graph), ...settings }
    graph.nodes.push(node)
    for (const [port, from] of Object.entries(inputs)) {
      graph.edges.push({ source: from, target: { node_id: node.id, port } })
    }
    return node
  }

  graph.input_slots.push({ id: 'audio_1', type: 'audio', label: '原音频输入' })
  const separate = input.scenario === 'binaural_dub'
    ? add('separate', { audio }, { model: input.separationModel })
    : null
  const vocals = separate ? source(separate, 'audio') : audio
  let subtitle: GraphSource
  if (input.subtitleInput) {
    graph.input_slots.push({ id: 'subtitle_1', type: 'subtitle', label: '原文字幕', language: input.sourceLang })
    subtitle = { kind: 'slot', slot_id: 'subtitle_1' }
  } else {
    subtitle = source(add('asr', { audio: vocals }, { source_lang: input.sourceLang }), 'subtitle')
  }

  if (input.scenario !== 'subtitle' && input.tier !== 'fast') {
    subtitle = source(add('delivery_detect', { audio: vocals, subtitle }), 'subtitle')
  }
  if (input.sourceLang !== input.targetLang) {
    const connection = input.translationConnection
    subtitle = source(add('translate', { subtitle }, {
      source_lang: input.sourceLang, target_lang: input.targetLang,
      ...(connection ? { provider: connection.provider, model: connection.model || null } : {}),
      options: { duration_aware: input.durationAware, ...(connection ? { connection_ref: connection.id } : {}) },
    }), 'subtitle')
  }

  if (input.scenario === 'subtitle') {
    // A subtitle-only workflow may have no audio consumer.
    if (!graph.edges.some(edge => edge.source.kind === 'slot' && edge.source.slot_id === 'audio_1')) graph.input_slots.shift()
    for (const format of ['srt', 'lrc']) {
      const node = add('export', { subtitle }, { options: { subtitle_format: format } })
      graph.outputs.push({ node_id: node.id, port: 'subtitle', label: format.toUpperCase() })
    }
    return { version: 2, graph, label: '字幕制作', description: '识别或导入字幕，按所选语言导出 SRT 和 LRC。' }
  }

  const tier = REMAKE_TIERS[input.tier]
  const speech = add('tts', { subtitle, reference_audio: input.recipeId ? audio : vocals }, {
    source_lang: input.sourceLang,
    target_lang: input.targetLang,
    options: {
      ...tier.options,
      max_atempo: 1.35,
      ...(input.recipeId ? { speech_recipe_id: input.recipeId } : {
        auto_clone: true, ...(input.tier !== 'fast' ? { reference_mode: 'per_style' } : {}),
      }),
      ...(input.tier === 'studio' && input.enableSeedVc
        ? { vc_refinement: { enabled: true, provider: 'seed_vc', diffusion_steps: 25 } } : {}),
    },
  })
  const finalNode = separate
    ? add('mix', { audio: source(separate, 'background'), speech: source(speech, 'audio') }, {
      options: tier.options.acoustic_options.loudness_match === 'per_cue' ? { adjust_tts_volume: false } : {},
    })
    : speech
  graph.outputs.push({ node_id: finalNode.id, port: 'audio', label: separate ? '双耳重制混音' : '配音' })
  return {
    version: 2, graph,
    label: `${input.scenario === 'binaural_dub' ? '双耳重制' : '台本配音'} · ${tier.label}`,
    description: tier.summary,
  }
}
