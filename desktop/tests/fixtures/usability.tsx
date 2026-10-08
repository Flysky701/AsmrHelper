import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import EnginesResources from '@/pages/EnginesResources'
import Settings from '@/pages/Settings'
import TaskCenter from '@/pages/TaskCenter'
import '@/index.css'

const settings = { connection_profiles: { llm: [{ id: 'mock', name: '测试翻译连接', provider: 'deepseek', base_url: 'https://example.invalid', model: 'mock-model', credential_configured: true }], active_llm: 'mock', removed_llm: [] },
  providers: { default_llm: 'deepseek', deepseek: { base_url: '', model: '', credential_configured: false }, openai: { base_url: '', model: '', credential_configured: false } },
  paths: { output_dir: '', vtt_dir: '', model_cache_dir: '', temp_dir: '' }, processing: {} }
const model = { model_id: 'mock-asr', display_name: '本地识别模型（模拟）', category: 'asr', kind: 'local', engine: 'qwen_asr', provider: 'qwen_asr', description: '用于识别录音中的原文。', supports_install: true, supports_remove: false, estimated_size_mb: 1200, runtime_profile: 'qwen_asr', required_assets: [], recommended_assets: [], required_system_tools: [] }
window.fetch = async (input, init) => {
  const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).pathname.replace(/^\/api\/v1/, '')
  const data: Record<string, unknown> = { '/settings': { settings }, '/models': [model], '/models/statuses': [{ model_id: 'mock-asr', installed: false, runtime_ready: false, loaded: false, status: 'not_installed', detail: '尚未安装', issues: [] }],
    '/models/sources': { roots: ['D:/fixture/shared-models'] }, '/resources/status': { resources: [] }, '/pipeline/presets': { presets: [] }, '/pipeline/presets/archived': { presets: [] },
    '/tasks': { tasks: [] }, '/batch-runs': { batches: [] }, '/speech/connections': { connections: [], defaults: [] }, '/speech/providers': { providers: [] } }
  if ((init?.method || 'GET') !== 'GET' || !(path in data)) throw new Error(`Blocked offline request: ${init?.method || 'GET'} ${path}`)
  return new Response(JSON.stringify(data[path]), { headers: { 'Content-Type': 'application/json' } })
}
function Fixture() {
  const [page, setPage] = useState('resources')
  return <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
    <nav style={{ padding: 8 }}>离线界面审查 · {['resources', 'settings', 'tasks'].map(id => <button key={id} onClick={() => setPage(id)}>{id}</button>)}</nav>
    <main style={{ flex: 1, minHeight: 0 }}>{page === 'resources' ? <EnginesResources /> : page === 'settings' ? <Settings /> : <TaskCenter />}</main>
  </div>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
