import { useAuth } from "../store/auth";
import type {
  Approval,
  Artifact,
  CostSummary,
  Note,
  Plan,
  Session,
  Task,
  WorktreeRow,
} from "./types";

export const API_BASE = "http://localhost:8787";
export const WS_BASE = "ws://localhost:8787";

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = useAuth.getState().token;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore - use statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listSessions: () => apiFetch<Session[]>("/api/sessions"),
  createSession: (title: string, base_branch?: string) =>
    apiFetch<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ title, base_branch: base_branch ?? null }),
    }),
  getSession: (id: string) => apiFetch<Session>(`/api/sessions/${id}`),
  closeSession: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/sessions/${id}/close`, { method: "POST" }),
  submitRequest: (id: string, text: string) =>
    apiFetch<{ status: string }>(`/api/sessions/${id}/request`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  sessionArtifacts: (id: string, kind?: string) =>
    apiFetch<Artifact[]>(
      `/api/sessions/${id}/artifacts${kind ? `?kind=${kind}` : ""}`
    ),
  getTask: (id: string) => apiFetch<Task & { artifacts: Artifact[] }>(`/api/tasks/${id}`),
  pendingApprovals: () => apiFetch<Approval[]>("/api/approvals"),
  decideApproval: (
    id: string,
    approved: boolean,
    reason?: string,
    editedPlan?: Plan
  ) =>
    apiFetch<{ ok: boolean; step_kind: string }>(
      `/api/approvals/${id}/decision`,
      {
        method: "POST",
        body: JSON.stringify({ approved, reason, edited_plan: editedPlan }),
      }
    ),
  cost: () => apiFetch<CostSummary>("/api/cost"),
  worktrees: () => apiFetch<WorktreeRow[]>("/api/worktrees"),
  cleanupWorktrees: () => apiFetch<{ removed: string[] }>("/api/worktrees/cleanup", { method: "POST" }),
  listNotes: () => apiFetch<Note[]>("/api/notes"),
  createNote: (text: string, kind = "note") =>
    apiFetch<{ id: string }>("/api/notes", { method: "POST", body: JSON.stringify({ text, kind }) }),
  deleteNote: (id: string) => apiFetch<{ ok: boolean }>(`/api/notes/${id}`, { method: "DELETE" }),
};

export { ApiError };
