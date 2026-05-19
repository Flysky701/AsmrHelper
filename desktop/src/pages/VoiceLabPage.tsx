import { useEffect, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { apiFetch } from "../api/client";

interface VoiceProfile {
  id: string;
  name: string;
  engine: string;
  available: boolean;
}

export function VoiceLabPage() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sidecarReady) return;
    apiFetch<VoiceProfile[]>("/api/v1/voice/profiles")
      .then((r) => {
        setProfiles(r);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, [sidecarReady]);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
        Voice Lab
      </h1>
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        Design, clone, and preview voice profiles for TTS synthesis.
      </p>

      {error && (
        <div className="rounded-lg px-4 py-3 text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--color-error)" }}>
          {error}
        </div>
      )}

      <section>
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--color-text-muted)" }}>
          Voice Profiles ({profiles.length})
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          {profiles.map((p) => (
            <div
              key={p.id}
              className="rounded-lg px-4 py-3"
              style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
            >
              <p className="text-sm font-medium" style={{ color: "var(--color-text)" }}>{p.name}</p>
              <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                {p.engine} · {p.available ? "available" : "unavailable"}
              </p>
            </div>
          ))}
          {profiles.length === 0 && !error && (
            <p className="text-sm col-span-3" style={{ color: "var(--color-text-muted)" }}>
              {sidecarReady ? "No voice profiles yet" : "Waiting for sidecar..."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
