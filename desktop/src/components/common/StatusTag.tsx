const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  pending: { bg: "var(--color-surface-hover)", text: "var(--color-text-muted)" },
  running: { bg: "rgba(52, 211, 153, 0.15)", text: "var(--color-accent)" },
  completed: { bg: "rgba(52, 211, 153, 0.25)", text: "var(--color-success)" },
  failed: { bg: "rgba(239, 68, 68, 0.15)", text: "var(--color-error)" },
  cancelled: { bg: "rgba(251, 191, 36, 0.15)", text: "var(--color-warning)" },
};

export function StatusTag({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.pending;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: style.bg, color: style.text }}
    >
      {status}
    </span>
  );
}
