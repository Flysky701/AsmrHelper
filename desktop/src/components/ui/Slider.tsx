interface SliderProps {
  value: number
  min?: number
  max?: number
  step?: number
  onChange: (value: number) => void
  label?: string
  formatValue?: (v: number) => string
}

export default function Slider({ value, min = 0, max = 100, step = 1, onChange, label, formatValue }: SliderProps) {
  const pct = ((value - min) / (max - min)) * 100

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {label && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
          <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--fg)' }}>{formatValue ? formatValue(value) : value}</span>
        </div>
      )}
      <div style={{ position: 'relative', height: 20, display: 'flex', alignItems: 'center' }}>
        <div style={{ position: 'absolute', width: '100%', height: 4, borderRadius: 2, background: 'var(--border)' }} />
        <div style={{ position: 'absolute', width: `${pct}%`, height: 4, borderRadius: 2, background: 'var(--accent)' }} />
        <input
          type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{ position: 'absolute', width: '100%', height: '100%', opacity: 0, cursor: 'pointer', margin: 0 }}
        />
        <div style={{
          position: 'absolute',
          left: `calc(${pct}% - 7px)`,
          width: 14, height: 14, borderRadius: '50%',
          background: 'var(--surface)',
          border: '2px solid var(--accent)',
          pointerEvents: 'none',
        }} />
      </div>
    </div>
  )
}
