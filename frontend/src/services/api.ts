import axios from "axios";

import type { HealthResponse } from "../types/health";
import type { Cluster, InvestigationRow } from "../types/investigation";

const TOKEN_KEY = "k8s-agent-token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the session just won't survive a reload */
  }
}

// Same origin: nginx (or the Vite dev server) proxies /api to the backend.
const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "" });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (axios.isAxiosError(err) && err.response?.status === 401 && !err.config?.url?.includes("/auth/login")) {
      window.dispatchEvent(new Event("k8s-agent:logout"));
    }
    return Promise.reject(err);
  },
);

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>("/api/health");
  return data;
}

export async function getAuthConfig(): Promise<{ mode: "password" | "none" }> {
  const { data } = await api.get("/api/auth/config");
  return data;
}

export async function login(password: string): Promise<string> {
  const { data } = await api.post("/api/auth/login", { password });
  return data.token;
}

export async function checkSession(): Promise<boolean> {
  try {
    await api.get("/api/auth/me");
    return true;
  } catch {
    return false;
  }
}

export async function getClusters(): Promise<{ current: string | null; clusters: Cluster[]; error: string | null }> {
  const { data } = await api.get("/api/clusters");
  return data;
}

export async function getNamespaces(cluster: string | null): Promise<{ namespaces: string[]; error: string | null; locked?: boolean }> {
  const { data } = await api.get("/api/namespaces", { params: cluster ? { cluster } : {} });
  return data;
}

export async function startInvestigation(cluster: string | null, namespace: string | null): Promise<InvestigationRow> {
  const { data } = await api.post("/api/investigations", { cluster, namespace });
  return data;
}

export async function cancelInvestigation(id: string): Promise<void> {
  await api.post(`/api/investigations/${id}/cancel`);
}

export async function listInvestigations(
  offset: number,
  limit: number,
  status?: string,
): Promise<{ rows: InvestigationRow[]; total: number }> {
  const { data } = await api.get("/api/investigations", { params: { offset, limit, ...(status ? { status } : {}) } });
  return data;
}

export async function getInvestigation(id: string): Promise<InvestigationRow> {
  const { data } = await api.get(`/api/investigations/${id}`);
  return data;
}

/** Live progress (Server-Sent Events). EventSource cannot send headers, so the token goes in the URL. */
export function watchInvestigation(id: string, onRow: (row: InvestigationRow) => void, onError: () => void): () => void {
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const source = new EventSource(`${base}/api/investigations/${id}/events?token=${encodeURIComponent(getToken())}`);
  source.onmessage = (e) => {
    const row = JSON.parse(e.data) as InvestigationRow;
    onRow(row);
    if (row.status !== "running") source.close();
  };
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) onError();
  };
  return () => source.close();
}

/** Turn any failure into a short, beginner-friendly message (no stack traces). */
export function friendlyError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.response?.status === 401) return "Your session expired. Please sign in again.";
    if (!err.response) return "Cannot reach the backend.\n\nPlease check that the backend is running.";
    if (err.response.status === 400) return String(err.response.data?.detail ?? "Invalid request.");
    return "The server hit an unexpected error. Please try again.";
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}
