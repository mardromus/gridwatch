import type { Dashboard, NetworkMap, OperatorBrief } from "./types";

const RETRY_DELAYS_MS = [0, 150, 350, 700, 1_200];

function isTransient(response: Response) {
  return response.status >= 500
    || (response.status === 404 && response.headers.get("x-render-routing") === "no-server");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let lastNetworkError: Error | null = null;
  for (const [attempt, delayMs] of RETRY_DELAYS_MS.entries()) {
    if (delayMs) await new Promise((resolve) => window.setTimeout(resolve, delayMs));

    let response: Response;
    try {
      response = await fetch(path, {
        headers: { "Content-Type": "application/json", ...init?.headers },
        ...init,
      });
    } catch (error) {
      lastNetworkError = error instanceof Error ? error : new Error("Network request failed");
      if (attempt < RETRY_DELAYS_MS.length - 1) continue;
      throw lastNetworkError;
    }

    if (response.ok) return response.json() as Promise<T>;
    if (isTransient(response) && attempt < RETRY_DELAYS_MS.length - 1) continue;

    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  throw lastNetworkError ?? new Error("Request failed after retries");
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