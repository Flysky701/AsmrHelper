import { useJobStore } from "../../stores/jobStore";
import { StatusTag } from "../common/StatusTag";
import { ProgressBar } from "../common/ProgressBar";

export function JobDetail() {
  const jobs = useJobStore((s) => s.jobs);
  const selectedJobId = useJobStore((s) => s.selectedJobId);
  const cancelJobs = useJobStore((s) => s.cancelJobs);

  const job = jobs.find((j) => j.job_id === selectedJobId);

  if (!job) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          Select a job to view details
        </p>
      </div>
    );
  }

  const duration =
    job.finished_at && job.started_at
      ? (job.finished_at - job.started_at).toFixed(1)
      : job.started_at
        ? ((Date.now() / 1000 - job.started_at).toFixed(1))
        : null;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold truncate" style={{ color: "var(--color-text)" }}>
          {job.source_name}
        </h2>
        <StatusTag status={job.status} />
      </div>

      {job.status === "running" && (
        <div>
          <ProgressBar value={job.progress} />
          <p className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>
            {job.stage} — {Math.round(job.progress * 100)}%
          </p>
        </div>
      )}

      {job.error && (
        <div
          className="rounded-lg px-3 py-2 text-xs"
          style={{ backgroundColor: "rgba(239, 68, 68, 0.1)", color: "var(--color-error)" }}
        >
          {job.error}
        </div>
      )}

      <div className="space-y-2">
        <DetailRow label="Job ID" value={job.job_id} />
        <DetailRow label="Source" value={job.source_file} />
        <DetailRow label="Type" value={job.job_type} />
        {job.preset_id && <DetailRow label="Preset" value={job.preset_id} />}
        {job.task_id && <DetailRow label="Task ID" value={job.task_id} />}
        {duration && <DetailRow label="Duration" value={`${duration}s`} />}
      </div>

      {Object.keys(job.resolved_options).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold mb-2" style={{ color: "var(--color-text-muted)" }}>
            Options
          </h3>
          <div
            className="rounded-lg px-3 py-2 text-xs font-mono overflow-auto max-h-40"
            style={{ backgroundColor: "var(--color-surface)", color: "var(--color-text-muted)" }}
          >
            {Object.entries(job.resolved_options).map(([k, v]) => (
              <div key={k}>
                <span style={{ color: "var(--color-accent)" }}>{k}</span>: {JSON.stringify(v)}
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(job.artifacts).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold mb-2" style={{ color: "var(--color-text-muted)" }}>
            Artifacts
          </h3>
          <div className="space-y-1">
            {Object.entries(job.artifacts).map(([name, path]) => (
              <div key={name} className="flex items-center gap-2 text-xs">
                <span
                  className="px-1.5 py-0.5 rounded text-xs"
                  style={{ backgroundColor: "var(--color-surface-hover)", color: "var(--color-accent)" }}
                >
                  {name}
                </span>
                <span className="truncate" style={{ color: "var(--color-text-muted)" }}>
                  {path}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {job.status === "pending" && (
        <button
          onClick={() => cancelJobs([job.job_id])}
          className="mt-auto px-3 py-1.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80"
          style={{ backgroundColor: "rgba(239, 68, 68, 0.15)", color: "var(--color-error)" }}
        >
          Cancel job
        </button>
      )}

      {job.status === "running" && (
        <p className="mt-auto text-xs" style={{ color: "var(--color-text-muted)" }}>
          Running jobs cannot be interrupted yet. Cancellation currently applies to pending jobs only.
        </p>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="shrink-0 w-16" style={{ color: "var(--color-text-muted)" }}>
        {label}
      </span>
      <span className="break-all" style={{ color: "var(--color-text)" }}>
        {value}
      </span>
    </div>
  );
}
