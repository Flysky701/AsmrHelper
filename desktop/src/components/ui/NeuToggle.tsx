interface NeuToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
}

export default function NeuToggle({
  checked,
  onChange,
  label,
  disabled = false,
}: NeuToggleProps) {
  return (
    <label
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <div
        onClick={() => !disabled && onChange(!checked)}
        style={{
          width: '44px',
          height: '24px',
          borderRadius: '12px',
          background: checked ? 'var(--accent)' : 'var(--bg-hover)',
          boxShadow: 'var(--shadow-pressed)',
          position: 'relative',
          transition: 'background 200ms',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: '18px',
            height: '18px',
            borderRadius: '50%',
            background: 'var(--bg-elevated)',
            boxShadow: 'var(--shadow-raised)',
            position: 'absolute',
            top: '3px',
            left: checked ? '23px' : '3px',
            transition: 'left 200ms',
          }}
        />
      </div>
      {label && (
        <span
          style={{
            fontSize: '0.875rem',
            color: 'var(--text-primary)',
            fontWeight: 500,
          }}
        >
          {label}
        </span>
      )}
    </label>
  )
}
