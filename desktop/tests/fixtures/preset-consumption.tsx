import { createRoot } from 'react-dom/client'
import VoiceLab from '@/pages/voice-lab/VoiceLab'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { useNavStore } from '@/stores/navStore'
import { createWorkflowStore } from '@/stores/workflowStore'
import type { GraphNode } from '@/domain/workflowGraph'
import type { SpeechRecipe, SpeechProvider } from '@/api/speech'
import '@/index.css'

const express = { delivery: { normal: { support: 'direct' }, soft: { support: 'direct' }, whisper: { support: 'direct' } }, emotion: { support: 'direct' }, pause: { support: 'postprocess' } }
const providers: SpeechProvider[] = [
  { provider_id: 'fish_audio', name: 'Fish Audio', remote: true, version: '1', connection_required: true, capabilities: express,
    modes: [{ id: 'hosted', models: ['s2.1-pro-free'], variant_kinds: ['hosted'], runtime_options: ['speed', 'temperature'], capabilities: express }],
    options_schema: { properties: { speed: { type: 'number', default: 1, minimum: .5, maximum: 2 }, temperature: { type: 'number', default: .7 } } } },
  { provider_id: 'qwen3', name: 'Qwen3 TTS', remote: false, version: '1', connection_required: false, capabilities: express,
    modes: [{ id: 'design', models: ['qwen3-voice-design'], variant_kinds: ['design'], runtime_options: ['temperature'], capabilities: express }],
    options_schema: { properties: { temperature: { type: 'number', default: .9 } } } },
]
const fish: SpeechRecipe = { id: 'fish-preset', name: '收藏的云端声音', revision: 1, voice_id: '', provider_id: 'fish_audio', model: 's2.1-pro-free', mode: 'hosted',
  connection_ref: 'fish-connection', language: 'auto', variant: { kind: 'hosted', value: 'mock-voice-id', style: 'normal' }, provider_options: { schema_version: 1, speed: 1.2 } }
const qwen: SpeechRecipe = { ...fish, id: 'qwen-preset', name: '本地设计声音', provider_id: 'qwen3', model: 'qwen3-voice-design', mode: 'design',
  connection_ref: 'engine-default-qwen3', variant: { kind: 'design', value: '温柔的成年声音', style: 'normal' }, provider_options: { schema_version: 1, temperature: .9 } }
const recipes = [fish, qwen]
const connections = [{ id: 'fish-connection', name: 'Fish 模拟连接', provider_id: 'fish_audio', deployment: 'cloud', credential_configured: true }]
const initial: GraphNode = { id: 'tts', kind: 'tts', provider: 'fish_audio', model: fish.model, target_lang: 'zh', options: { speech_recipe_id: fish.id }, provider_options: {} }
const legacy: GraphNode = { ...initial, provider: 'qwen3', model: qwen.model, options: { speech_source: { mode: 'design', variant: qwen.variant, connection_ref: qwen.connection_ref, provider_options: qwen.provider_options } } }
const requests: string[] = []
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url)
  const path = url.pathname.replace(/^\/api\/v1/, ''), method = init?.method || 'GET'
  requests.push(`${method} ${path}`)
  if (method === 'POST' && path === '/speech/rules') {
    const body = JSON.parse(String(init?.body)), saved = { ...body, variant: { ...body.variant, style: 'normal' }, id: `mock-${recipes.length}`, voice_id: '', revision: 1 }
    recipes.push(saved)
    return Response.json(saved)
  }
  const data: Record<string, unknown> = {
    '/speech/providers': { providers }, '/speech/rules': { recipes }, '/speech/references': { assets: [] },
    '/speech/library': { voices: [], recipes, assets: [], experiments: [], takes: [], plans: [], selections: [], assemblies: [], connections },
    '/speech/connections': { connections, defaults: [] }, '/tasks': { tasks: [] }, '/speech/cleanup/trash': { receipts: [] },
    '/speech/fish-clones': { clones: [] }, '/speech/connections/fish-connection/voices': { items: [], page: 1, page_size: 20, has_more: false, notice: '离线模拟' },
  }
  if (method !== 'GET' || !(path in data)) throw new Error(`Blocked unexpected request: ${method} ${path}`)
  return Response.json(data[path])
}
const fixtureWorkflow = createWorkflowStore(undefined, { getItem: () => null, setItem: () => {}, removeItem: () => {} })
fixtureWorkflow.setState({ runtimeGraph: { version: 2, nodes: [initial], input_slots: [], edges: [], outputs: [] } })
function Fixture() {
  const node = fixtureWorkflow(state => state.runtimeGraph!.nodes[0]!), setNode = fixtureWorkflow.getState().updateRuntimeNode
  const page = useNavStore(state => state.activePage)
  return <main style={{ maxWidth: 1100, margin: 'auto', padding: 24 }}><h1>音色预设 · 离线验收</h1><p>所有请求为内存 mock，无云端调用。</p>
    {page === 'voice-lab' ? <VoiceLab /> : <>
      <nav><button onClick={() => setNode(structuredClone(initial))}>加载云端节点</button><button onClick={() => setNode(structuredClone(legacy))}>加载旧本地节点</button>
        <button onClick={() => setNode({ ...structuredClone(legacy), options: { ...legacy.options, future_unknown: { keep: true } } })}>加载未知旧数据</button></nav>
      <GraphNodeParameters node={node} onChange={setNode} />
      <details><summary>当前节点数据</summary><pre aria-label="当前节点数据">{JSON.stringify(node, null, 2)}</pre></details>
    </>}
    <details><summary>模拟请求记录</summary><pre>{requests.join('\n')}</pre></details>
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
