import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon?: ReactNode
  message: string
}

export default function EmptyState({ icon, message }: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        padding: '32px 16px',
        color: 'var(--text-secondary)',
      }}
    >
      {icon && <span style={{ fontSize: '24px', opacity: 0.5 }}>{icon}</span>}
      <span style={{ fontSize: '0.875rem' }}>{message}</span>
    </div>
  )
}
