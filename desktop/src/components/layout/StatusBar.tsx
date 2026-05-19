import { useAppStore } from "../../stores/appStore";

export function StatusBar() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);
  const sidecarPort = useAppStore((s) => s.sidecarPort);

  return (
    <footer
      className="h-7 flex items-center justify-between px-4 border-t text-xs shrink-0"
      style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
    >
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: sidecarReady ? "var(--color-success)" : "var(--color-error)" }}
        />
        <span>Python sidecar: {sidecarReady ? `Running (port ${sidecarPort})` : "Disconnected"}</span>
      </div>
      <span>AsmrHelper Desktop</span>
    </footer>
  );
}
