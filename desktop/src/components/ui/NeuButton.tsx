import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

interface NeuButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  children: ReactNode
}

const sizeClasses: Record<Size, string> = {
  sm: 'px-3 py-1 text-sm',
  md: 'px-5 py-2 text-base',
  lg: 'px-7 py-3 text-lg',
}

const variantStyles: Record<Variant, React.CSSProperties> = {
  primary: {
    background: 'var(--accent)',
    color: 'var(--accent-text)',
  },
  secondary: {
    background: 'var(--bg-surface)',
    color: 'var(--text-primary)',
    border: '1.5px solid var(--bg-hover)',
  },
  danger: {
    background: 'var(--color-error)',
    color: '#fff',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-secondary)',
    boxShadow: 'none',
  },
}

export default function NeuButton({
  variant = 'secondary',
  size = 'md',
  children,
  disabled,
  style,
  ...props
}: NeuButtonProps) {
  return (
    <button
      disabled={disabled}
      style={{
        borderRadius: 'var(--radius-button)',
        boxShadow: variant === 'ghost' ? 'none' : 'var(--shadow-raised)',
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        transition: 'box-shadow 150ms, transform 150ms, opacity 150ms',
        border: 'none',
        outline: 'none',
        ...variantStyles[variant],
        ...style,
      }}
      className={`${sizeClasses[size]} active:translate-y-px`}
      onMouseDown={(e) => {
        if (!disabled && variant !== 'ghost') {
          e.currentTarget.style.boxShadow = 'var(--shadow-pressed)'
          e.currentTarget.style.transform = 'translateY(1px)'
        }
      }}
      onMouseUp={(e) => {
        if (!disabled && variant !== 'ghost') {
          e.currentTarget.style.boxShadow = 'var(--shadow-raised)'
          e.currentTarget.style.transform = 'translateY(0)'
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && variant !== 'ghost') {
          e.currentTarget.style.boxShadow = 'var(--shadow-raised)'
          e.currentTarget.style.transform = 'translateY(0)'
        }
      }}
      {...props}
    >
      {children}
    </button>
  )
}
