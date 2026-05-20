import type { LogEntry as LogEntryType, LogLevel } from '@/stores/logStore'
import { NeuTag } from '@/components/ui'

interface LogEntryProps {
  entry: LogEntryType
}

const LEVEL_VARIANT: Record<LogLevel, 'info' | 'warning' | 'error'> = {
  info: 'info',
  warn: 'warning',
  error: 'error',
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const h = d.getHours().toString().padStart(2, '0')
  const m = d.getMinutes().toString().padStart(2, '0')
  const s = d.getSeconds().toString().padStart(2, '0')
  return `${h}:${m}:${s}`
}

export default function LogEntry({ entry }: LogEntryProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '8px',
        padding: '4px 12px',
        fontSize: '0.75rem',
        lineHeight: '1.5',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
          flexShrink: 0,
          fontSize: '0.6875rem',
        }}
      >
        {formatTime(entry.timestamp)}
      </span>
      <NeuTag variant={LEVEL_VARIANT[entry.level]}>
        {entry.level.toUpperCase()}
      </NeuTag>
      <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>
        {entry.content}
      </span>
    </div>
  )
}
