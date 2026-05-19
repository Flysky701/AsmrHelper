import { apiFetch } from "./client";
import type { JobCreateRequest, JobListResponse, Job, DiscoverResponse } from "./types";

export async function createJobs(req: JobCreateRequest): Promise<JobListResponse> {
  return apiFetch("/api/v1/jobs", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function listJobs(status?: string): Promise<JobListResponse> {
  const qs = status ? `?status=${status}` : "";
  return apiFetch(`/api/v1/jobs${qs}`);
}

export async function getJob(jobId: string): Promise<Job> {
  return apiFetch(`/api/v1/jobs/${jobId}`);
}

export async function startJobs(maxConcurrent = 2): Promise<JobListResponse> {
  return apiFetch(`/api/v1/jobs/start?max_concurrent=${maxConcurrent}`, {
    method: "POST",
  });
}

export async function cancelJobs(jobIds: string[]): Promise<JobListResponse> {
  return apiFetch("/api/v1/jobs/cancel", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export async function discoverFiles(directory: string): Promise<DiscoverResponse> {
  return apiFetch("/api/v1/jobs/discover", {
    method: "POST",
    body: JSON.stringify({ directory }),
  });
}
