import { useAppStore } from "../stores/appStore";

export function SettingsPage() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);
  const sidecarPort = useAppStore((s) => s.sidecarPort);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
        Settings
      </h1>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
          Sidecar
        </h2>
        <div
          className="rounded-lg px-4 py-3 space-y-2"
          style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
        >
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: sidecarReady ? "var(--color-success)" : "var(--color-error)" }}
            />
            <span className="text-sm" style={{ color: "var(--color-text)" }}>
              {sidecarReady ? `Connected (port ${sidecarPort})` : "Disconnected"}
            </span>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold" style={{ color: "var(--color-text-muted)" }}>
          About
        </h2>
        <div
          className="rounded-lg px-4 py-3"
          style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
        >
          <p className="text-sm" style={{ color: "var(--color-text)" }}>AsmrHelper Desktop v0.3.0</p>
          <p className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>
            Audio processing pipeline with ASR, translation, and TTS synthesis.
          </p>
        </div>
      </section>
    </div>
  );
}
