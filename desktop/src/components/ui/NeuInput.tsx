import type { InputHTMLAttributes } from 'react'

interface NeuInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: string
}

export default function NeuInput({ label, style, ...props }: NeuInputProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {label && (
        <label
          style={{
            fontSize: '0.875rem',
            fontWeight: 500,
            color: 'var(--text-secondary)',
          }}
        >
          {label}
        </label>
      )}
      <input
        style={{
          background: 'var(--bg-base)',
          borderRadius: 'var(--radius-button)',
          boxShadow: 'var(--shadow-pressed)',
          border: 'none',
          outline: 'none',
          padding: '10px 14px',
          fontSize: '1rem',
          color: 'var(--text-primary)',
          transition: 'box-shadow 200ms',
          ...style,
        }}
        onFocus={(e) => {
          e.currentTarget.style.boxShadow =
            'var(--shadow-pressed), 0 0 0 2px var(--accent)'
        }}
        onBlur={(e) => {
          e.currentTarget.style.boxShadow = 'var(--shadow-pressed)'
        }}
        {...props}
      />
    </div>
  )
}
