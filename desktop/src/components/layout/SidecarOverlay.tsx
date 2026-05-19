import { useAppStore } from "../../stores/appStore";

export function SidecarOverlay() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);

  if (sidecarReady) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ backgroundColor: "rgba(15, 17, 23, 0.85)" }}
    >
      <div className="flex items-center gap-3 mb-4">
        <div
          className="w-3 h-3 rounded-full animate-pulse"
          style={{ backgroundColor: "var(--color-warning)" }}
        />
        <span className="text-lg font-medium" style={{ color: "var(--color-text)" }}>
          Starting Python sidecar...
        </span>
      </div>
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        Please wait while the backend initializes.
      </p>
    </div>
  );
}
