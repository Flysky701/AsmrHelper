import TaskQueue from '@/components/sidebar/TaskQueue'
import SystemLog from '@/components/sidebar/SystemLog'

export default function RightSidebar() {
  return (
    <aside
      style={{
        width: '280px',
        background: 'var(--bg-surface)',
        borderLeft: '1px solid rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ flex: 6, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <TaskQueue />
      </div>
      <div
        style={{
          height: '1px',
          background: 'rgba(0,0,0,0.06)',
          margin: '0 8px',
        }}
      />
      <div style={{ flex: 4, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <SystemLog />
      </div>
    </aside>
  )
}
