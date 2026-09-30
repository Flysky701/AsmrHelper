import { createRoot } from 'react-dom/client'
import Workbench from '@/pages/Workbench'
import TaskCenter from '@/pages/TaskCenter'
import { useNavStore } from '@/stores/navStore'
import { useTaskStore } from '@/stores/taskStore'
import type { Task } from '@/stores/taskStore'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import { useSpeechDraftStore } from '@/stores/speechDraftStore'
import '@/index.css'

// Only fixture data. No filesystem access, native dialog, credential or model call.
const history: Task = {
  id: 'history-pipeline-1', serverTaskId: 'pipeline-1', jobType: 'pipeline',
  sourceName: 'history-translation.wav', sourcePath: 'D:/fixture/history-translation.wav',
  status: 'failed', stage: 'translate', progress: 40, message: 'Historical translation failed',
  detail: '', errorMessage: 'HISTORICAL_TRANSLATION_ERROR',
  error: { code: 'TASK_EXECUTION_FAILED', message: 'HISTORICAL_TRANSLATION_ERROR' },
  createdAt: Date.parse('2026-09-20T01:02:03Z'), finishedAt: Date.parse('2026-09-20T01:04:05Z'),
  historical: true, params: {},
}
useTaskStore.setState({ tasks: [history], selectedTaskId: history.id, filter: 'all' })
const workbench = useWorkbenchStore.getState()
workbench.reset()
workbench.updateParam('sourceLang', 'ja')
workbench.updateParam('targetLang', 'zh')
workbench.updateParam('ttsEngine', 'mock_speech')
workbench.addInputItems([{ path: 'D:/fixture/target.zh.vtt', name: 'target.zh.vtt', kind: 'subtitle',
  size: 128, companionPaths: [], subtitleSummary: { language: 'zh', valid: true, reason: '' } }])
workbench.toggleStage('tts')
workbench.setBinding('tts', 'text', { kind: 'asset', path: 'D:/fixture/target.zh.vtt' })
useSpeechDraftStore.getState().setEngine({ providerId: 'mock_speech', model: 'fixture', mode: 'hosted',
  value: 'preserved-voice-id', connectionRef: '', providerOptions: { schema_version: 1 } })
useNavStore.getState().openTaskCenter('tasks')

Object.assign(window, { __taskDetail: {
  snapshot: () => {
    const state = useTaskStore.getState()
    const task = state.tasks.find(item => item.id === state.selectedTaskId)
    return { selectedId: state.selectedTaskId, selectedServerId: task?.serverTaskId,
      page: useNavStore.getState().activePage,
      tasks: state.tasks.map(item => ({ id: item.id, serverId: item.serverTaskId, status: item.status })) }
  },
  // Simulates an explicit selection by another existing task entry point while
  // TaskCenter stays mounted, so its category/status filters are not reset by remount.
  selectServerTask: (serverId: string) => {
    const task = useTaskStore.getState().tasks.find(item => item.serverTaskId === serverId)
    if (!task) throw new Error(`Unknown fixture task: ${serverId}`)
    useTaskStore.getState().selectTask(task.id)
  },
  seedLocalFailure: () => {
    const task: Task = { id: 'local-submit-failure', jobType: 'pipeline', sourceName: 'local-submit.vtt',
      sourcePath: 'D:/fixture/local-submit.vtt', status: 'failed', stage: 'prepare', progress: 0,
      message: 'Local submission failed', detail: '', errorMessage: 'LOCAL_SUBMISSION_ERROR',
      createdAt: Date.parse('2026-09-21T02:03:04Z'), params: {}, specLoaded: true }
    useTaskStore.setState(state => ({ tasks: [...state.tasks, task] }))
    useTaskStore.getState().selectTask(task.id)
  },
} })

function Fixture() {
  const page = useNavStore(state => state.activePage)
  return <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
    <nav aria-label="Fixture navigation" style={{ padding: 8, display: 'flex', gap: 10 }}>
      <button onClick={() => useNavStore.getState().setPage('workbench')}>Fixture Workbench</button>
      <button onClick={() => useNavStore.getState().openTaskCenter('tasks')}>Fixture TaskCenter</button>
    </nav>
    <main style={{ flex: 1, minHeight: 0 }}>
      {page === 'workbench' ? <Workbench /> : <TaskCenter />}
    </main>
  </div>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
