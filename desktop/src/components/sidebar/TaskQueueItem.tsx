import type { Task } from '@/stores/taskStore'
import StatusBadge from '@/components/shared/StatusBadge'
import { NeuProgress } from '@/components/ui'

interface TaskQueueItemProps {
  task: Task
  onClick: () => void
}

export default function TaskQueueItem({ task, onClick }: TaskQueueItemProps) {
  const displayName =
    task.sourceName.length > 20
      ? task.sourceName.slice(0, 17) + '...'
      : task.sourceName

  return (
    <div
      onClick={onClick}
      style={{
        padding: '8px 12px',
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        borderBottom: '1px solid rgba(0,0,0,0.04)',
        transition: 'background 150ms',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--bg-hover)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        }}
      >
        <span
          style={{
            fontSize: '0.8125rem',
            color: 'var(--text-primary)',
            fontWeight: 500,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            flex: 1,
          }}
          title={task.sourceName}
        >
          {displayName}
        </span>
        <StatusBadge status={task.status} />
      </div>
      {(task.status === 'running' || task.progress > 0) && (
        <NeuProgress value={task.progress} />
      )}
    </div>
  )
}
