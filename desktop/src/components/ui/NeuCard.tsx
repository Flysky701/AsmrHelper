import type { CSSProperties, ReactNode } from 'react'

interface NeuCardProps {
  children: ReactNode
  hoverable?: boolean
  className?: string
  style?: CSSProperties
  onClick?: () => void
}

export default function NeuCard({
  children,
  hoverable = false,
  className = '',
  style,
  onClick,
}: NeuCardProps) {
  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-surface)',
        borderRadius: 'var(--radius-card)',
        boxShadow: 'var(--shadow-raised)',
        padding: '16px',
        transition: hoverable
          ? 'transform 200ms ease-out, box-shadow 200ms ease-out'
          : undefined,
        cursor: hoverable ? 'pointer' : undefined,
        ...style,
      }}
      className={className}
      onMouseEnter={
        hoverable
          ? (e) => {
              e.currentTarget.style.transform = 'translateY(-2px)'
              e.currentTarget.style.boxShadow =
                '-6px -6px 18px rgba(255,255,255,0.85), 6px 6px 18px rgba(0,0,0,0.12)'
            }
          : undefined
      }
      onMouseLeave={
        hoverable
          ? (e) => {
              e.currentTarget.style.transform = 'translateY(0)'
              e.currentTarget.style.boxShadow = 'var(--shadow-raised)'
            }
          : undefined
      }
    >
      {children}
    </div>
  )
}
