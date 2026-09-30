import { createRoot } from 'react-dom/client'
import WorkbenchSpeech from '../../src/components/WorkbenchSpeech'
import { useSpeechDraftStore } from '../../src/stores/speechDraftStore'
import '../../src/index.css'

useSpeechDraftStore.getState().setEngine({ providerId: 'fish_audio', model: 's2-pro',
  mode: 'hosted', value: 'user-kept-id', connectionRef: '', providerOptions: { schema_version: 1 } })
const record = () => {}
createRoot(document.getElementById('root')!).render(<main style={{ maxWidth: 880, margin: '24px auto', padding: 20 }}>
  <h1 style={{ marginBottom: 24 }}>配音配置</h1>
  <WorkbenchSpeech disabled={false} language="zh" preferredProvider="fish_audio" onChange={record} />
</main>)
