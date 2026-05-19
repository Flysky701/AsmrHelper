import { useState } from "react";
import { useJobStore } from "../../stores/jobStore";
import { StatusTag } from "../common/StatusTag";
import { ProgressBar } from "../common/ProgressBar";

const FILTER_TABS = ["all", "pending", "running", "completed", "failed"] as const;

export function JobQueue() {
  const jobs = useJobStore((s) => s.jobs);
  const selectedJobId = useJobStore((s) => s.selectedJobId);
  const selectJob = useJobStore((s) => s.selectJob);
  const [filter, setFilter] = useState<string>("all");

  const filtered = filter === "all" ? jobs : jobs.filter((j) => j.status === filter);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-4 pt-3 pb-2">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className="px-3 py-1 rounded-lg text-xs font-medium transition-colors"
            style={{
              backgroundColor: filter === tab ? "var(--color-surface-hover)" : "transparent",
              color: filter === tab ? "var(--color-accent)" : "var(--color-text-muted)",
            }}
          >
            {tab}
            {tab === "all" ? ` (${jobs.length})` : ` (${jobs.filter((j) => j.status === tab).length})`}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-4 pb-4 space-y-1">
        {filtered.length === 0 && (
          <p className="text-sm text-center py-8" style={{ color: "var(--color-text-muted)" }}>
            No jobs{filter !== "all" ? ` with status "${filter}"` : ""}.
          </p>
        )}
        {filtered.map((job) => (
          <button
            key={job.job_id}
            onClick={() => selectJob(job.job_id)}
            className="w-full text-left rounded-lg px-3 py-2.5 transition-colors"
            style={{
              backgroundColor: selectedJobId === job.job_id ? "var(--color-surface-hover)" : "transparent",
              border: selectedJobId === job.job_id ? "1px solid var(--color-accent)" : "1px solid transparent",
            }}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium truncate" style={{ color: "var(--color-text)" }}>
                {job.source_name}
              </span>
              <StatusTag status={job.status} />
            </div>
            {job.status === "running" && (
              <div className="mt-1.5">
                <ProgressBar value={job.progress} />
                <p className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>
                  {job.stage} — {Math.round(job.progress * 100)}%
                </p>
              </div>
            )}
            {job.error && (
              <p className="text-xs mt-1 truncate" style={{ color: "var(--color-error)" }}>
                {job.error}
              </p>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
