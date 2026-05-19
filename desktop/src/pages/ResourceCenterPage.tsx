import { useEffect, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { usePolling } from "../hooks/usePolling";
import {
  listModels,
  listModelStatuses,
  getResourceStatus,
  type ModelSummary,
  type ModelStatus,
  type ResourceStatus,
} from "../api/resources";

export function ResourceCenterPage() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [statuses, setStatuses] = useState<ModelStatus[]>([]);
  const [resources, setResources] = useState<ResourceStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = async () => {
    try {
      const [m, s, r] = await Promise.all([
        listModels(),
        listModelStatuses(),
        getResourceStatus(),
      ]);
      setModels(m);
      setStatuses(s);
      setResources(r.resources);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (sidecarReady) fetchAll();
  }, [sidecarReady]);

  usePolling(fetchAll, 10000, sidecarReady);

  const statusMap = Object.fromEntries(statuses.map((s) => [s.model_id, s]));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
        Resource Center
      </h1>

      {error && (
        <div className="rounded-lg px-4 py-3 text-sm" style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--color-error)" }}>
          {error}
        </div>
      )}

      {/* System resources */}
      <section>
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--color-text-muted)" }}>
          System Resources
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          {resources.map((r) => (
            <div
              key={r.name}
              className="rounded-lg px-4 py-3"
              style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: r.available ? "var(--color-success)" : "var(--color-error)" }}
                />
                <span className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
                  {r.name}
                </span>
              </div>
              <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>{r.detail}</p>
            </div>
          ))}
          {resources.length === 0 && !error && (
            <p className="text-sm col-span-3" style={{ color: "var(--color-text-muted)" }}>
              {sidecarReady ? "Loading..." : "Waiting for sidecar..."}
            </p>
          )}
        </div>
      </section>

      {/* Models */}
      <section>
        <h2 className="text-sm font-semibold mb-3" style={{ color: "var(--color-text-muted)" }}>
          Models ({models.length})
        </h2>
        <div className="space-y-1">
          {models.map((m) => {
            const st = statusMap[m.model_id];
            return (
              <div
                key={m.model_id}
                className="flex items-center justify-between rounded-lg px-4 py-2.5"
                style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: "var(--color-text)" }}>
                    {m.display_name}
                  </p>
                  <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                    {m.category} / {m.kind} — {m.backend}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-4">
                  {st && (
                    <span
                      className="inline-flex items-center px-2 py-0.5 rounded text-xs"
                      style={{
                        backgroundColor: st.status === "loaded" ? "rgba(52,211,153,0.15)" : "var(--color-surface-hover)",
                        color: st.status === "loaded" ? "var(--color-accent)" : "var(--color-text-muted)",
                      }}
                    >
                      {st.status}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
          {models.length === 0 && !error && (
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
              {sidecarReady ? "Loading..." : "Waiting for sidecar..."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
