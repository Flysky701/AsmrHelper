import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  children: ReactNode
}

export default function Button({ variant = 'secondary', size = 'md', children, disabled, style, ...props }: ButtonProps) {
  const base: React.CSSProperties = {
    fontFamily: 'var(--font-body)',
    fontSize: 13,
    fontWeight: 500,
    borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border)',
    background: 'var(--surface)',
    color: 'var(--fg)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: size === 'sm' ? '5px 10px' : '7px 14px',
    transition: 'background 0.12s, border-color 0.12s',
  }

  if (variant === 'primary') {
    base.background = 'var(--accent)'
    base.color = 'white'
    base.borderColor = 'var(--accent)'
  } else if (variant === 'ghost') {
    base.background = 'transparent'
    base.border = 'none'
    base.color = 'var(--muted)'
  } else if (variant === 'danger') {
    base.background = 'var(--error)'
    base.color = 'white'
    base.borderColor = 'var(--error)'
  }

  return (
    <button disabled={disabled} style={{ ...base, ...style }} {...props}>
      {children}
    </button>
  )
}
