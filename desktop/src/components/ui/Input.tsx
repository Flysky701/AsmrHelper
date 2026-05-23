import type { InputHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

export default function Input({ label, style, ...props }: InputProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {label && (
        <label style={{ fontSize: 11, fontWeight: 500, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {label}
        </label>
      )}
      <input
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 13,
          padding: '7px 10px',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)',
          background: 'var(--surface)',
          color: 'var(--fg)',
          width: '100%',
          outline: 'none',
          ...style,
        }}
        {...props}
      />
    </div>
  )
}
