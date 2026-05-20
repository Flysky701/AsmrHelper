import { useTaskStore } from '@/stores/taskStore'
import { useNavStore } from '@/stores/navStore'
import TaskQueueItem from './TaskQueueItem'
import EmptyState from '@/components/shared/EmptyState'
import { NeuButton } from '@/components/ui'

export default function TaskQueue() {
  const tasks = useTaskStore((s) => s.tasks)
  const selectTask = useTaskStore((s) => s.selectTask)
  const startAll = useTaskStore((s) => s.startAll)
  const pauseAll = useTaskStore((s) => s.pauseAll)
  const setPage = useNavStore((s) => s.setPage)

  const handleTaskClick = (id: string) => {
    selectTask(id)
    setPage('tasks')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid rgba(0,0,0,0.05)',
        }}
      >
        <span
          style={{
            fontWeight: 600,
            fontSize: '0.8125rem',
            color: 'var(--text-primary)',
          }}
        >
          任务队列
        </span>
        <div style={{ display: 'flex', gap: '4px' }}>
          <NeuButton size="sm" onClick={startAll}>
            全部开始
          </NeuButton>
          <NeuButton size="sm" onClick={pauseAll}>
            全部暂停
          </NeuButton>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {tasks.length === 0 ? (
          <EmptyState message="暂无任务" />
        ) : (
          tasks.map((task) => (
            <TaskQueueItem
              key={task.id}
              task={task}
              onClick={() => handleTaskClick(task.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}
