interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
}

export default function Toggle({ checked, onChange, label, disabled = false }: ToggleProps) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1 }}>
      <div
        onClick={(e) => { e.preventDefault(); if (!disabled) onChange(!checked) }}
        style={{
          width: 36,
          height: 20,
          borderRadius: 10,
          background: checked ? 'var(--accent)' : 'var(--border)',
          position: 'relative',
          transition: 'background 0.2s',
          flexShrink: 0,
        }}
      >
        <div style={{
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: 'white',
          position: 'absolute',
          top: 3,
          left: checked ? 19 : 3,
          transition: 'left 0.2s',
          boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
        }} />
      </div>
      {label && <span style={{ fontSize: 13, color: 'var(--fg)', fontWeight: 500 }}>{label}</span>}
    </label>
  )
}
