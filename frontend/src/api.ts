import type { Dashboard, NetworkMap, OperatorBrief } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  network: () => request<NetworkMap>("/api/network"),
  simulate: (kind: string) =>
    request<{ simulation_id?: string; suppressed: boolean }>("/api/simulator/inject", {
      method: "POST",
      body: JSON.stringify({ kind }),
    }),
  repair: (simulationId: string) =>
    request(`/api/simulator/${simulationId}/repair`, { method: "POST" }),
  reset: () => request("/api/simulator/reset", { method: "POST" }),
  transition: (incidentId: string, action: string, crew?: string) =>
    request(`/api/incidents/${incidentId}/transition`, {
      method: "POST",
      body: JSON.stringify({ action, crew }),
    }),
  brief: (incidentId: string, language: string) =>
    request<OperatorBrief>(`/api/incidents/${incidentId}/brief`, {
      method: "POST",
      body: JSON.stringify({ language }),
    }),
};