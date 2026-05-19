import { useState, useCallback } from "react";

interface Props {
  onFilesSelected: (files: string[]) => void;
}

export function FileDropZone({ onFilesSelected }: Props) {
  const [text, setText] = useState("");

  const normalizePath = useCallback((value: string) => {
    const trimmed = value.trim();
    if (trimmed.length >= 2 && (trimmed.startsWith('"') && trimmed.endsWith('"') || trimmed.startsWith("'") && trimmed.endsWith("'"))) {
      return trimmed.slice(1, -1).trim();
    }
    return trimmed;
  }, []);

  const handleSubmit = useCallback(() => {
    const files = text
      .split("\n")
      .map((l) => normalizePath(l))
      .filter(Boolean);
    if (files.length > 0) {
      onFilesSelected(files);
      setText("");
    }
  }, [text, onFilesSelected, normalizePath]);

  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium" style={{ color: "var(--color-text-muted)" }}>
        Input files (one path per line)
      </label>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        className="w-full rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1"
        style={{
          backgroundColor: "var(--color-surface)",
          color: "var(--color-text)",
          borderColor: "var(--color-border)",
          border: "1px solid var(--color-border)",
        }}
        placeholder="D:\music\track01.mp3&#10;D:\music\track02.wav"
      />
      <button
        onClick={handleSubmit}
        disabled={!text.trim()}
        className="px-3 py-1.5 rounded-lg text-sm font-medium transition-opacity disabled:opacity-40"
        style={{ backgroundColor: "var(--color-accent)", color: "#0f1117" }}
      >
        Add to queue
      </button>
    </div>
  );
}
