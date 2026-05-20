import { useRef, useEffect } from 'react'
import { useLogStore } from '@/stores/logStore'
import LogEntryComp from './LogEntry'
import EmptyState from '@/components/shared/EmptyState'

export default function SystemLog() {
  const logs = useLogStore((s) => s.logs)
  const levelFilter = useLogStore((s) => s.levelFilter)
  const scrollRef = useRef<HTMLDivElement>(null)

  const filtered = logs.filter((l) => levelFilter.includes(l.level))

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [filtered.length])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div
        style={{
          padding: '8px 12px',
          borderBottom: '1px solid rgba(0,0,0,0.05)',
          fontWeight: 600,
          fontSize: '0.8125rem',
          color: 'var(--text-primary)',
        }}
      >
        系统日志
      </div>
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.length === 0 ? (
          <EmptyState message="暂无日志" />
        ) : (
          filtered.map((entry) => <LogEntryComp key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  )
}
