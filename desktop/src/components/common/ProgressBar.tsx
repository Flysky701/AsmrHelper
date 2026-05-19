export function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div
      className={`h-1.5 rounded-full overflow-hidden ${className}`}
      style={{ backgroundColor: "var(--color-surface-hover)" }}
    >
      <div
        className="h-full rounded-full transition-all duration-300"
        style={{ width: `${pct}%`, backgroundColor: "var(--color-accent)" }}
      />
    </div>
  );
}
