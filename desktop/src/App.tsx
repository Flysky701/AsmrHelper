import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import { Sidebar } from "./components/layout/Sidebar";
import { StatusBar } from "./components/layout/StatusBar";
import { SidecarOverlay } from "./components/layout/SidecarOverlay";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { WorkbenchPage } from "./pages/WorkbenchPage";
import { TaskCenterPage } from "./pages/TaskCenterPage";
import { ResourceCenterPage } from "./pages/ResourceCenterPage";
import { VoiceLabPage } from "./pages/VoiceLabPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useAppStore } from "./stores/appStore";

export default function App() {
  const setSidecarReady = useAppStore((s) => s.setSidecarReady);

  useEffect(() => {
    const unlistenReady = listen<number>("sidecar:ready", (event) => {
      console.log("[app] sidecar:ready port=", event.payload);
      setSidecarReady(true, event.payload);
    });

    const unlistenError = listen<string>("sidecar:error", (event) => {
      console.error("[app] sidecar:error", event.payload);
      setSidecarReady(false, null);
    });

    return () => {
      unlistenReady.then((fn) => fn());
      unlistenError.then((fn) => fn());
    };
  }, [setSidecarReady]);

  return (
    <BrowserRouter>
      <div className="flex h-screen" style={{ backgroundColor: "var(--color-bg)" }}>
        <Sidebar />
        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-auto">
            <ErrorBoundary>
              <Routes>
                <Route path="/" element={<WorkbenchPage />} />
                <Route path="/task-center" element={<TaskCenterPage />} />
                <Route path="/resource-center" element={<ResourceCenterPage />} />
                <Route path="/voice-lab" element={<VoiceLabPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </ErrorBoundary>
          </div>
          <StatusBar />
        </main>
        <SidecarOverlay />
      </div>
    </BrowserRouter>
  );
}
