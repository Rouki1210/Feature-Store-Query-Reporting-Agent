import type { AskResponse, FeatureSummary, HealthResponse } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export function ask(question: string, sessionId?: string | null): Promise<AskResponse> {
  return fetch(`${BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  }).then((r) => json<AskResponse>(r));
}

export function features(q: string, limit = 50): Promise<FeatureSummary[]> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return fetch(`${BASE}/features?${params}`).then((r) => json<FeatureSummary[]>(r));
}

export function health(): Promise<HealthResponse> {
  return fetch(`${BASE}/health`).then((r) => json<HealthResponse>(r));
}
