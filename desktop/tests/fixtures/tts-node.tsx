import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import type { GraphNode } from '@/domain/workflowGraph'
import type { SpeechProvider, SpeechRecipe } from '@/api/speech'
import '@/index.css'

const sources = (kind: string) => ({ kind, presets: [], default: null, required: true, allow_custom: true, description: `${kind} 离线测试` })
const providers: SpeechProvider[] = [
  { provider_id: 'qwen3', name: 'Qwen3 TTS', remote: false, version: '1', connection_required: false, capabilities: {},
    modes: [{ id: 'reference', models: ['qwen3-base'], variant_kinds: ['reference'], voice_sources: sources('reference') },
      { id: 'design', models: ['qwen3-voice-design'], variant_kinds: ['design'], voice_sources: sources('design') }],
    options_schema: { properties: { x_vector_only_mode: { type: 'boolean', default: false, applies_to_modes: ['reference'] },
      temperature: { type: 'number', default: .9 }, instructions: { type: 'string', applies_to_modes: ['design'] } } } },
  { provider_id: 'fish_audio', name: 'Fish Audio', remote: true, version: '1', connection_required: true, capabilities: {},
    modes: [{ id: 'hosted', models: ['s2.1-pro-free'], variant_kinds: ['hosted'], voice_sources: sources('hosted') }],
    options_schema: { properties: { speed: { type: 'number', default: 1 }, temperature: { type: 'number', default: .7 } } } },
]
const recipe: SpeechRecipe = { id: 'fish-preset', name: 'Fish 测试预设', revision: 1, voice_id: '', provider_id: 'fish_audio', model: 's2.1-pro-free', mode: 'hosted',
  connection_ref: 'fish-connection', language: 'zh', variant: { kind: 'hosted', value: 'mock-voice-id', style: 'normal' }, provider_options: { schema_version: 1, speed: 1.2 } }
const initial: GraphNode = { id: 'tts', kind: 'tts', provider: 'qwen3', model: 'qwen3-base', target_lang: 'zh',
  options: { speech_source: { mode: 'reference', variant: { kind: 'reference', value: '' }, connection_ref: 'engine-default-qwen3', provider_options: { schema_version: 1 } } }, provider_options: {} }
const requests: string[] = []
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url)
  const path = url.pathname.replace(/^\/api\/v1/, ''), method = init?.method || 'GET'
  requests.push(`${method} ${path}`)
  const data: Record<string, unknown> = { '/speech/providers': { providers }, '/speech/rules': { recipes: [recipe] }, '/speech/references': { assets: [] },
    '/speech/connections': { connections: [{ id: 'fish-connection', provider_id: 'fish_audio', name: 'Fish 测试连接', deployment: 'cloud' },
      { id: 'fish-second', provider_id: 'fish_audio', name: 'Fish 第二连接', deployment: 'cloud' }], defaults: [] },
    '/speech/connections/fish-connection/voices': { items: [{ id: 'mock-first-voice', name: '第一连接候选' }], page: 1, page_size: 20, has_more: false, notice: '离线模拟列表' },
    '/speech/connections/fish-second/voices': { items: [{ id: 'mock-second-voice', name: '第二连接候选' }], page: 1, page_size: 20, has_more: false, notice: '离线模拟列表' }, '/models': [] }
  if (method !== 'GET' || !(path in data)) throw new Error(`Blocked unexpected request: ${method} ${path}`)
  return new Response(JSON.stringify(data[path]), { headers: { 'Content-Type': 'application/json' } })
}
function Fixture() {
  const [node, setNode] = useState(initial)
  return <main style={{ maxWidth: 700, padding: 24, margin: 'auto' }}><h1>TTS 配音参数 · 离线模拟</h1>
    <p>使用真实节点编辑器，全部 API 请求由本页拦截；不会调用后端或合成。</p>
    <nav><button onClick={() => setNode(structuredClone(initial))}>重置 Qwen 节点</button>
      <button onClick={() => setNode({ ...structuredClone(initial), model: 'qwen3-voice-design' })}>载入模式不兼容节点</button>
      <button onClick={() => setNode({ ...structuredClone(initial), provider: 'removed-provider' })}>载入未知引擎节点</button>
      <button onClick={() => setNode({ ...structuredClone(initial), options: { speech_recipe_id: recipe.id } })}>载入预设引擎错配节点</button></nav>
    <GraphNodeParameters node={node} onChange={setNode}/>
    <details open><summary>当前节点数据</summary><pre aria-label="当前节点数据">{JSON.stringify(node, null, 2)}</pre></details>
    <pre aria-label="模拟请求记录">{requests.join('\n')}</pre>
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
