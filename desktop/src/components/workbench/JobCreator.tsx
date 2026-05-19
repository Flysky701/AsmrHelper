import { useState } from "react";
import { FileDropZone } from "./FileDropZone";
import { useJobStore } from "../../stores/jobStore";
import { useAppStore } from "../../stores/appStore";

export function JobCreator() {
  const createJobs = useJobStore((s) => s.createJobs);
  const startQueue = useJobStore((s) => s.startQueue);
  const loading = useJobStore((s) => s.loading);
  const sidecarReady = useAppStore((s) => s.sidecarReady);

  const [sourceLang, setSourceLang] = useState("ja");
  const [targetLang, setTargetLang] = useState("zh");
  const [ttsEngine, setTtsEngine] = useState("edge");

  const handleFiles = async (files: string[]) => {
    await createJobs(files, { source_lang: sourceLang, target_lang: targetLang, tts_engine: ttsEngine });
    await startQueue();
  };

  return (
    <div className="flex flex-col gap-4 p-4 h-full">
      <h2 className="text-sm font-semibold" style={{ color: "var(--color-text)" }}>
        Create Job
      </h2>

      <FileDropZone onFilesSelected={handleFiles} />

      <div className="space-y-3">
        <div>
          <label className="text-xs" style={{ color: "var(--color-text-muted)" }}>Source language</label>
          <select
            value={sourceLang}
            onChange={(e) => setSourceLang(e.target.value)}
            className="w-full mt-1 rounded-lg px-2 py-1.5 text-sm"
            style={{ backgroundColor: "var(--color-surface)", color: "var(--color-text)", border: "1px solid var(--color-border)" }}
          >
            <option value="ja">Japanese</option>
            <option value="zh">Chinese</option>
            <option value="en">English</option>
          </select>
        </div>
        <div>
          <label className="text-xs" style={{ color: "var(--color-text-muted)" }}>Target language</label>
          <select
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            className="w-full mt-1 rounded-lg px-2 py-1.5 text-sm"
            style={{ backgroundColor: "var(--color-surface)", color: "var(--color-text)", border: "1px solid var(--color-border)" }}
          >
            <option value="zh">Chinese</option>
            <option value="en">English</option>
            <option value="ja">Japanese</option>
          </select>
        </div>
        <div>
          <label className="text-xs" style={{ color: "var(--color-text-muted)" }}>TTS engine</label>
          <select
            value={ttsEngine}
            onChange={(e) => setTtsEngine(e.target.value)}
            className="w-full mt-1 rounded-lg px-2 py-1.5 text-sm"
            style={{ backgroundColor: "var(--color-surface)", color: "var(--color-text)", border: "1px solid var(--color-border)" }}
          >
            <option value="edge">Edge TTS</option>
            <option value="qwen3">Qwen3 TTS</option>
          </select>
        </div>
      </div>

      {!sidecarReady && (
        <p className="text-xs mt-auto" style={{ color: "var(--color-error)" }}>
          Waiting for Python sidecar...
        </p>
      )}

      {loading && (
        <p className="text-xs" style={{ color: "var(--color-accent)" }}>
          Creating jobs...
        </p>
      )}
    </div>
  );
}
