interface NeuSliderProps {
  value: number
  min?: number
  max?: number
  step?: number
  onChange: (value: number) => void
  label?: string
  showValue?: boolean
  formatValue?: (value: number) => string
}

export default function NeuSlider({
  value,
  min = 0,
  max = 100,
  step = 1,
  onChange,
  label,
  showValue = false,
  formatValue,
}: NeuSliderProps) {
  const pct = ((value - min) / (max - min)) * 100

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      {(label || showValue) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          {label && (
            <span
              style={{
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
              }}
            >
              {label}
            </span>
          )}
          {showValue && (
            <span
              style={{
                fontSize: '0.875rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-primary)',
              }}
            >
              {formatValue ? formatValue(value) : value}
            </span>
          )}
        </div>
      )}
      <div style={{ position: 'relative', height: '24px', display: 'flex', alignItems: 'center' }}>
        <div
          style={{
            position: 'absolute',
            width: '100%',
            height: '8px',
            borderRadius: '4px',
            background: 'var(--bg-base)',
            boxShadow: 'var(--shadow-pressed)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            width: `${pct}%`,
            height: '8px',
            borderRadius: '4px',
            background: 'var(--accent)',
          }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{
            position: 'absolute',
            width: '100%',
            height: '100%',
            opacity: 0,
            cursor: 'pointer',
            margin: 0,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: `calc(${pct}% - 8px)`,
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: 'var(--bg-elevated)',
            boxShadow: 'var(--shadow-raised)',
            pointerEvents: 'none',
          }}
        />
      </div>
    </div>
  )
}
