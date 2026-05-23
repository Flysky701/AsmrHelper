import type { ReactNode } from 'react'

interface CardProps {
  title?: string
  count?: string
  children: ReactNode
  style?: React.CSSProperties
}

export default function Card({ title, count, children, style }: CardProps) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', ...style }}>
      {title && (
        <div style={{ padding: '12px 16px', fontSize: 13, fontWeight: 600, borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>{title}</span>
          {count && <span style={{ fontWeight: 400, color: 'var(--muted)', fontSize: 12 }}>{count}</span>}
        </div>
      )}
      {children}
    </div>
  )
}
