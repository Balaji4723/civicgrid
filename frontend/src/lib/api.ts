import type { User } from "./types";

export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    return `http://${host}:8000`;
  }
  return "http://localhost:8000";
}

export const API = getApiBaseUrl();

export class ApiError extends Error {
  status: number;
  code: string | undefined;
  detail: Record<string, unknown>;
  constructor(status: number, message: string, code?: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export const session = {
  token: (): string | null => (typeof window === "undefined" ? null : window.localStorage.getItem("cg_token")),
  user: (): User | null => {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem("cg_user");
    return raw ? (JSON.parse(raw) as User) : null;
  },
  save: (token: string, user: User) => {
    window.localStorage.setItem("cg_token", token);
    window.localStorage.setItem("cg_user", JSON.stringify(user));
  },
  clear: () => {
    window.localStorage.removeItem("cg_token");
    window.localStorage.removeItem("cg_user");
  },
};

async function send(path: string, init: { method: string; body?: BodyInit; json?: boolean }): Promise<Response> {
  const headers: Record<string, string> = {};
  const token = session.token();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.json) headers["Content-Type"] = "application/json";   // never set for FormData: the browser adds the multipart boundary
  const baseUrl = getApiBaseUrl();
  try {
    return await fetch(`${baseUrl}${path}`, { method: init.method, headers, body: init.body });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${baseUrl}. Is the backend running?`, "NETWORK");
  }
}


/** Authenticated download (evidence files need the bearer token, so <img src> cannot fetch them directly). */
export async function apiBlob(path: string): Promise<Blob> {
  const res = await send(path, { method: "GET" });
  if (!res.ok) {
    const d = ((await res.json().catch(() => ({}))) as { detail?: Record<string, unknown> }).detail ?? {};
    throw new ApiError(res.status, String(d.message ?? "Could not load the file"), String(d.error ?? ""), d);
  }
  return res.blob();
}

export const apiUpload = <T,>(path: string, form: FormData) => api<T>(path, { method: "POST", form });

export async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const res = await send(path, opts.form
    ? { method: opts.method ?? "POST", body: opts.form }
    : { method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"), body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined, json: opts.body !== undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      session.clear();
      window.location.href = "/login";
    }
    if (d && typeof d === "object" && !Array.isArray(d)) {
      const o = d as Record<string, unknown>;
      throw new ApiError(res.status, String(o.message ?? "Request failed"), String(o.error ?? ""), o);
    }
    if (Array.isArray(d)) {
      // FastAPI validation errors
      const first = d[0] as { loc?: unknown[]; msg?: string } | undefined;
      const field = first?.loc?.slice(-1)[0];
      const msg = (first?.msg ?? "is invalid").replace(/^Value error, /, "");
      throw new ApiError(res.status, field && field !== "body" ? `Check the form: ${field} - ${msg}.` : `Check the form: ${msg}.`, "VALIDATION");
    }
    throw new ApiError(res.status, "Request failed");
  }
  return data as T;
}
