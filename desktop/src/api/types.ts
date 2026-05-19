export interface Job {
  job_id: string;
  job_type: string;
  source_file: string;
  source_name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  stage: string;
  progress: number;
  preset_id: string;
  resolved_options: Record<string, unknown>;
  artifacts: Record<string, string>;
  primary_output: string | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  task_id: string | null;
}

export interface JobListResponse {
  jobs: Job[];
  total: number;
}

export interface JobCreateItem {
  source_file: string;
  source_name?: string;
}

export interface JobCreateRequest {
  items: JobCreateItem[];
  preset_id?: string;
  resolved_options?: Record<string, unknown>;
}

export interface DiscoverResponse {
  files: string[];
  count: number;
}
