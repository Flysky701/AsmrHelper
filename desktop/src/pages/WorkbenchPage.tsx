import { useEffect } from "react";
import { JobCreator } from "../components/workbench/JobCreator";
import { JobQueue } from "../components/workbench/JobQueue";
import { JobDetail } from "../components/workbench/JobDetail";
import { useJobStore } from "../stores/jobStore";
import { useAppStore } from "../stores/appStore";
import { usePolling } from "../hooks/usePolling";

export function WorkbenchPage() {
  const fetchJobs = useJobStore((s) => s.fetchJobs);
  const sidecarReady = useAppStore((s) => s.sidecarReady);

  useEffect(() => {
    if (sidecarReady) fetchJobs();
  }, [sidecarReady, fetchJobs]);

  usePolling(fetchJobs, 3000, sidecarReady);

  return (
    <div className="flex h-full">
      {/* Left: job creator */}
      <div
        className="w-64 shrink-0 border-r overflow-auto"
        style={{ borderColor: "var(--color-border)" }}
      >
        <JobCreator />
      </div>

      {/* Center: job queue */}
      <div className="flex-1 min-w-0">
        <JobQueue />
      </div>

      {/* Right: job detail */}
      <div
        className="w-80 shrink-0 border-l overflow-auto"
        style={{ borderColor: "var(--color-border)" }}
      >
        <JobDetail />
      </div>
    </div>
  );
}
