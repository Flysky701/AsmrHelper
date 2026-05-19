import { create } from "zustand";
import type { Job } from "../api/types";
import * as jobsApi from "../api/jobs";

interface JobState {
  jobs: Job[];
  selectedJobId: string | null;
  loading: boolean;
  error: string | null;

  fetchJobs: () => Promise<void>;
  selectJob: (jobId: string | null) => void;
  createJobs: (files: string[], options?: Record<string, unknown>) => Promise<void>;
  startQueue: () => Promise<void>;
  cancelJobs: (jobIds: string[]) => Promise<void>;
  clearError: () => void;
}

export const useJobStore = create<JobState>((set, get) => ({
  jobs: [],
  selectedJobId: null,
  loading: false,
  error: null,

  fetchJobs: async () => {
    try {
      const resp = await jobsApi.listJobs();
      set({ jobs: resp.jobs, error: null });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  selectJob: (jobId) => set({ selectedJobId: jobId }),

  createJobs: async (files, options) => {
    set({ loading: true, error: null });
    try {
      const items = files.map((f) => ({
        source_file: f,
        source_name: f.split(/[/\\]/).pop() || f,
      }));
      await jobsApi.createJobs({
        items,
        resolved_options: options || {},
      });
      await get().fetchJobs();
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  startQueue: async () => {
    set({ loading: true, error: null });
    try {
      await jobsApi.startJobs();
      await get().fetchJobs();
    } catch (e) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  cancelJobs: async (jobIds) => {
    try {
      await jobsApi.cancelJobs(jobIds);
      await get().fetchJobs();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  clearError: () => set({ error: null }),
}));
