import type { ReactNode } from 'react'

type TagVariant = 'default' | 'info' | 'success' | 'warning' | 'error'

interface NeuTagProps {
  variant?: TagVariant
  children: ReactNode
}

const variantColors: Record<TagVariant, { bg: string; text: string }> = {
  default: { bg: 'var(--bg-hover)', text: 'var(--text-secondary)' },
  info: { bg: 'var(--accent)', text: 'var(--accent-text)' },
  success: { bg: '#d1fae5', text: '#065f46' },
  warning: { bg: '#fef3c7', text: '#92400e' },
  error: { bg: '#fee2e2', text: '#991b1b' },
}

export default function NeuTag({ variant = 'default', children }: NeuTagProps) {
  const colors = variantColors[variant]
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 10px',
        borderRadius: 'var(--radius-tag)',
        background: colors.bg,
        color: colors.text,
        fontSize: '0.75rem',
        fontWeight: 600,
        lineHeight: '1.5',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}
