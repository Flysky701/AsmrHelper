import { create } from "zustand";

type Page = "workbench" | "task-center" | "resource-center" | "voice-lab" | "settings";

interface AppState {
  sidecarReady: boolean;
  sidecarPort: number | null;
  currentPage: Page;
  setSidecarReady: (ready: boolean, port: number | null) => void;
  setPage: (page: Page) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidecarReady: false,
  sidecarPort: null,
  currentPage: "workbench",
  setSidecarReady: (ready, port) => set({ sidecarReady: ready, sidecarPort: port }),
  setPage: (page) => set({ currentPage: page }),
}));
