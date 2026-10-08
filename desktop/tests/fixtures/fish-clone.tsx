// Standalone offline fixture. Every fetch is intercepted; never contacts the backend or Fish.
import { createRoot } from 'react-dom/client'
import FishClonePanel from '../../src/pages/voice-lab/FishClonePanel'
import type { FishClone } from '../../src/api/fishClones'
import '../../src/index.css'
import '../../src/pages/voice-lab/VoiceLab.css'

const records: FishClone[] = []
const calls: string[] = []
const scenario = new URLSearchParams(location.search).get('scenario') || 'success'
Object.assign(window, { fishCloneTest: { calls, records } })
window.fetch = async (input, init) => {
  const url = new URL(String(input)).pathname, method = init?.method || 'GET'
  calls.push(method + ' ' + url)
  const log = document.getElementById('mock-calls')
  if (log) log.textContent = calls.join('\n')
  const body = init?.body ? JSON.parse(String(init.body)) : {}
  let data: unknown
  if (url.endsWith('/preview')) data = { ...body, token: 'mock-review', endpoint: 'https://api.fish.audio/model',
    asset_name: '离线测试录音', bytes: 44100, duration: 3, transcript: '这是已经核对的测试原文。', visibility: 'private' }
  else if (url.endsWith('/fish-clones') && method === 'POST') {
    if (scenario === 'rejected') return new Response(JSON.stringify({ detail: '模拟：素材校验失败，请重新预览。' }), { status: 422, headers: { 'Content-Type': 'application/json' } })
    const item = { ...body, id: body.request_id, state: scenario === 'unknown' ? 'unknown' : scenario === 'failed' ? 'failed' : 'created',
      remote_voice_id: scenario === 'unknown' ? null : 'mock-voice-id',
      message: scenario === 'unknown' ? '模拟响应丢失：结果未知，请先核查，不要重复创建。' : scenario === 'failed' ? '模拟：远程处理失败。' : '', recipe_id: null }
    records.push(item); data = item
  } else if (url.endsWith('/refresh')) {
    records[0]!.state = 'trained'; data = records[0]
  } else if (url.endsWith('/rule')) {
    records[0]!.recipe_id = 'saved-rule'; data = { id: 'saved-rule', model: 's2.1-pro-free', mode: 'hosted', variant: { kind: 'hosted', value: 'mock-voice-id' } }
  } else if (method === 'DELETE') {
    const item = records.find(record => url.endsWith('/' + record.id))!
    item.deleted = true; item.updated_at = new Date().toISOString(); data = item
  } else if (url.endsWith('/restore')) {
    const item = records.find(record => url.endsWith('/' + record.id + '/restore'))!
    item.deleted = false; data = item
  } else if (url.endsWith('/fish-clones') && method === 'GET') data = { items: records }
  else throw new Error('Unexpected offline request: ' + url)
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

createRoot(document.getElementById('root')!).render(<main className="speech-lab" style={{ maxWidth: 1050, margin: '24px auto' }}>
  <nav aria-label="离线测试场景"><strong>全模拟，不调用真实服务：</strong>{[['success', '成功'], ['unknown', '结果未知'], ['failed', '远程失败'], ['rejected', '请求被拒绝']].map(([key, label]) => <a key={key} href={`?scenario=${key}`} style={{ marginRight: 14 }}>{label}</a>)}</nav>
  <FishClonePanel active assets={[{ id: 'sample', name: '离线测试录音', path: '', transcript: '这是已经核对的测试原文。', language: 'zh', confirmed: true }]}
    connections={[{ id: 'fish', provider_id: 'fish_audio', name: 'Fish 测试连接', deployment: 'cloud' }]}
    onSaved={async recipe => { document.getElementById('saved')!.textContent = `已保存 ${recipe.model} ${recipe.variant.value}` }} />
  <p id="saved" role="status" />
  <pre id="mock-calls" aria-label="模拟调用记录" />
</main>)
