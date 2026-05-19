import { useAppStore } from "../stores/appStore";

function getBaseUrl(): string {
  const port = useAppStore.getState().sidecarPort;
  if (!port) {
    throw new Error("Sidecar not connected — no port available");
  }
  return `http://127.0.0.1:${port}`;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${body}`);
  }
  return resp.json();
}
