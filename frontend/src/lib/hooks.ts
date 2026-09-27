"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, session } from "./api";
import { getHomeForUser } from "./nav";
import type { Role, User } from "./types";

export const HOME: Record<Role, string> = {
  WORKER: "/worker", FACILITY: "/receiving", MUNICIPAL_ADMIN: "/municipal", CITIZEN: "/citizen",
};

/** Redirects to /login if signed out, or to the user's own portal if this page is not for their role. */
export function useGuard(allow: Role[]): User | null {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    const u = session.user();
    if (!u || !session.token()) { router.replace("/login"); return; }
    if (!allow.includes(u.role)) { router.replace(getHomeForUser(u)); return; }
    setUser(u);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return user;
}


export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    try { setData(await fnRef.current()); setError(null); }
    catch (e) { setError(e instanceof ApiError ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (enabled) void reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [enabled, ...deps]);
  return { data, error, loading, reload, setData };
}

export const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "-";
export const short = (h: string, n = 8) => `${h.slice(0, n)}…`;
