import { apiFetch } from "./client";

export interface ModelSummary {
  model_id: string;
  kind: string;
  category: string;
  backend: string;
  display_name: string;
}

export interface ModelStatus {
  model_id: string;
  status: string;
  detail: string;
}

export interface ResourceStatus {
  name: string;
  available: boolean;
  detail: string;
  metadata: Record<string, unknown>;
}

export async function listModels(kind?: string): Promise<ModelSummary[]> {
  const qs = kind ? `?kind=${kind}` : "";
  return apiFetch(`/api/v1/models${qs}`);
}

export async function listModelStatuses(): Promise<ModelStatus[]> {
  return apiFetch("/api/v1/models/statuses");
}

export async function getResourceStatus(): Promise<{ resources: ResourceStatus[] }> {
  return apiFetch("/api/v1/resources/status");
}
