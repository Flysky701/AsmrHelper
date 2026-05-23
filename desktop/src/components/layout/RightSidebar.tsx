import TaskQueue from '@/components/sidebar/TaskQueue'
import SystemLog from '@/components/sidebar/SystemLog'

export default function RightSidebar() {
  return (
    <aside
      style={{
        width: 280,
        background: 'var(--surface)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <div style={{ flex: 6, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <TaskQueue />
      </div>
      <div
        style={{
          height: 1,
          background: 'var(--border)',
          margin: '0 8px',
        }}
      />
      <div style={{ flex: 4, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <SystemLog />
      </div>
    </aside>
  )
}
