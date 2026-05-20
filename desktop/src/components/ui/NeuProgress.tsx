interface NeuProgressProps {
  value: number // 0..1
  className?: string
}

export default function NeuProgress({ value, className = '' }: NeuProgressProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div
      className={className}
      style={{
        height: '8px',
        borderRadius: '4px',
        background: 'var(--bg-base)',
        boxShadow: 'var(--shadow-pressed)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: '100%',
          borderRadius: '4px',
          background: 'var(--accent)',
          transition: 'width 300ms ease-out',
        }}
      />
    </div>
  )
}
