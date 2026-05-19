import { useEffect, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { usePolling } from "../hooks/usePolling";
import type { Job } from "../api/types";
import { listJobs as fetchJobs } from "../api/jobs";
import { StatusTag } from "../components/common/StatusTag";
import { ProgressBar } from "../components/common/ProgressBar";

export function TaskCenterPage() {
  const sidecarReady = useAppStore((s) => s.sidecarReady);
  const [jobs, setJobs] = useState<Job[]>([]);

  const load = async () => {
    try {
      const resp = await fetchJobs();
      setJobs(resp.jobs);
    } catch {}
  };

  useEffect(() => {
    if (sidecarReady) load();
  }, [sidecarReady]);

  usePolling(load, 5000, sidecarReady);

  const completed = jobs.filter((j) => j.status === "completed").length;
  const failed = jobs.filter((j) => j.status === "failed").length;
  const running = jobs.filter((j) => j.status === "running").length;

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
        Task Center
      </h1>

      <div className="flex gap-4">
        <StatCard label="Total" value={jobs.length} />
        <StatCard label="Running" value={running} color="var(--color-accent)" />
        <StatCard label="Completed" value={completed} color="var(--color-success)" />
        <StatCard label="Failed" value={failed} color="var(--color-error)" />
      </div>

      <div className="space-y-1">
        {jobs.map((job) => (
          <div
            key={job.job_id}
            className="flex items-center justify-between rounded-lg px-4 py-2.5"
            style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium truncate" style={{ color: "var(--color-text)" }}>
                  {job.source_name}
                </span>
                <StatusTag status={job.status} />
              </div>
              {job.status === "running" && (
                <div className="mt-1.5 max-w-md">
                  <ProgressBar value={job.progress} />
                  <p className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>
                    {job.stage}
                  </p>
                </div>
              )}
            </div>
            <span className="text-xs shrink-0 ml-4" style={{ color: "var(--color-text-muted)" }}>
              {new Date(job.created_at * 1000).toLocaleString()}
            </span>
          </div>
        ))}
        {jobs.length === 0 && (
          <p className="text-sm text-center py-8" style={{ color: "var(--color-text-muted)" }}>
            {sidecarReady ? "No tasks yet" : "Waiting for sidecar..."}
          </p>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div
      className="rounded-lg px-4 py-3 min-w-24"
      style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}
    >
      <p className="text-2xl font-semibold" style={{ color: color || "var(--color-text)" }}>
        {value}
      </p>
      <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>{label}</p>
    </div>
  );
}
